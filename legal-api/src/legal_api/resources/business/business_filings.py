# Copyright © 2019 Province of British Columbia
#
# Licensed under the Apache License, Version 2.0 (the 'License');
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an 'AS IS' BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Searching on a business entity.

Provides all the search and retrieval from the business entity datastore.
"""
from http import HTTPStatus
from typing import Tuple, Union

import requests  # noqa: I001; grouping out of order to make both pylint & isort happy
from requests import exceptions  # noqa: I001; grouping out of order to make both pylint & isort happy
from flask import current_app, g, jsonify, request
from flask_babel import _
from flask_jwt_oidc import JwtManager
from flask_restplus import Resource, cors
from werkzeug.local import LocalProxy

import legal_api.reports
from legal_api.exceptions import BusinessException
from legal_api.models import Address, Business, Filing, RegistrationBootstrap, User, db
from legal_api.models.colin_event_id import ColinEventId
from legal_api.schemas import rsbc_schemas
from legal_api.services import COLIN_SVC_ROLE, STAFF_ROLE, RegistrationBootstrapService, authorized, queue
from legal_api.services.filings import validate
from legal_api.services.utils import get_str
from legal_api.utils import datetime
from legal_api.utils.auth import jwt
from legal_api.utils.legislation_datetime import LegislationDatetime
from legal_api.utils.util import cors_preflight

from .api_namespace import API
# noqa: I003; the multiple route decorators cause an erroneous error in line space counting


@cors_preflight('GET, POST, PUT, DELETE, PATCH')
@API.route('/<string:identifier>/filings', methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'])
@API.route('/<string:identifier>/filings/<int:filing_id>', methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS', 'PATCH'])
class ListFilingResource(Resource):
    """Business Filings service."""

    @staticmethod
    @cors.crossdomain(origin='*')
    @jwt.requires_auth
    def get(identifier, filing_id=None):  # pylint: disable=too-many-return-statements;
        # fix this while refactoring this whole module
        """Return a JSON object with meta information about the Service."""
        if identifier.startswith('T'):
            q = db.session.query(Filing). \
                filter(Filing.temp_reg == identifier)

            if filing_id:
                q = q.filter(Filing.id == filing_id)

            rv = q.one_or_none()

            if not rv:
                return jsonify({'message': f'{identifier} no filings found'}), HTTPStatus.NOT_FOUND
            return jsonify(rv.json)

        business = Business.find_by_identifier(identifier)

        if not business:
            return jsonify(filings=[]), HTTPStatus.NOT_FOUND

        if filing_id:
            rv = db.session.query(Business, Filing). \
                filter(Business.id == Filing.business_id).\
                filter(Business.identifier == identifier).\
                filter(Filing.id == filing_id).\
                one_or_none()
            if not rv:
                return jsonify({'message': f'{identifier} no filings found'}), HTTPStatus.NOT_FOUND

            if str(request.accept_mimetypes) == 'application/pdf':
                report_type = request.args.get('type', None)
                if rv[1].filing_type == 'incorporationApplication':
                    ListFilingResource._populate_business_info_to_filing(rv[1], business)
                return legal_api.reports.get_pdf(rv[1], report_type)

            return jsonify(rv[1].json)

        # Does it make sense to get a PDF of all filings?
        if str(request.accept_mimetypes) == 'application/pdf':
            return jsonify({'message': _('Cannot return a single PDF of multiple filing submissions.')}),\
                HTTPStatus.NOT_ACCEPTABLE

        rv = []
        filings = Filing.get_filings_by_status(business.id, [Filing.Status.COMPLETED.value, Filing.Status.PAID.value])
        for filing in filings:
            rv.append(filing.json)

        return jsonify(filings=rv)

    @staticmethod
    @cors.crossdomain(origin='*')
    @jwt.requires_auth
    def post(identifier, filing_id=None):
        """Create a new filing for the business."""
        return ListFilingResource.put(identifier, filing_id)

    @staticmethod
    @cors.crossdomain(origin='*')
    @jwt.requires_auth
    def put(identifier, filing_id):  # pylint: disable=too-many-return-statements
        """Modify an incomplete filing for the business."""
        # basic checks
        err_msg, err_code = ListFilingResource._put_basic_checks(identifier, filing_id, request)
        if err_msg:
            return jsonify({'errors': [err_msg, ]}), err_code
        json_input = request.get_json()

        # check authorization
        if not authorized(identifier, jwt, action=['edit']):
            return jsonify({'message':
                            f'You are not authorized to submit a filing for {identifier}.'}), \
                HTTPStatus.UNAUTHORIZED

        # get query params
        draft = (request.args.get('draft', None).lower() == 'true') \
            if request.args.get('draft', None) else False
        only_validate = (request.args.get('only_validate', None).lower() == 'true') \
            if request.args.get('only_validate', None) else False

        # validate filing
        if not draft and not ListFilingResource._is_before_epoch_filing(json_input,
                                                                        Business.find_by_identifier(identifier)):
            if identifier.startswith('T'):
                business_validate = RegistrationBootstrap.find_by_identifier(identifier)
            else:
                business_validate = Business.find_by_identifier(identifier)
            err = validate(business_validate, json_input)
            # err_msg, err_code = ListFilingResource._validate_filing_json(request)
            if err or only_validate:
                if err:
                    json_input['errors'] = err.msg
                    return jsonify(json_input), err.code
                return jsonify(json_input), HTTPStatus.OK

        # save filing, if it's draft only then bail
        user = User.get_or_create_user_by_jwt(g.jwt_oidc_token_info)
        try:
            business, filing, err_msg, err_code = ListFilingResource._save_filing(request, identifier, user, filing_id)
            if err_msg or draft:
                reply = filing.json if filing else json_input
                reply['errors'] = [err_msg, ]
                return jsonify(reply), err_code or \
                    (HTTPStatus.CREATED if (request.method == 'POST') else HTTPStatus.ACCEPTED)
        except Exception as err:
            print(err)

        # complete filing
        response, response_code = ListFilingResource.complete_filing(business, filing, draft)
        if response:
            return response, response_code

        # all done
        return jsonify(filing.json),\
            (HTTPStatus.CREATED if (request.method == 'POST') else HTTPStatus.ACCEPTED)

    @staticmethod
    @cors.crossdomain(origin='*')
    @jwt.requires_auth
    def delete(identifier, filing_id=None):
        """Delete a filing from the business."""
        if not filing_id:
            return ({'message':
                     _('No filing id provided for:') + identifier},
                    HTTPStatus.BAD_REQUEST)

        # check authorization
        if not authorized(identifier, jwt, action=['edit']):
            return jsonify({'message':
                            _('You are not authorized to delete a filing for:') + identifier}),\
                HTTPStatus.UNAUTHORIZED

        if identifier.startswith('T'):
            filing = Filing.get_temp_reg_filing(identifier, filing_id)
        else:
            filing = Business.get_filing_by_id(identifier, filing_id)

        if not filing:
            return jsonify({'message': _('Filing Not Found.')}), HTTPStatus.NOT_FOUND

        try:
            filing.delete()
        except BusinessException as err:
            return jsonify({'errors': [{'error': err.error}, ]}), err.status_code

        if identifier.startswith('T'):
            bootstrap = RegistrationBootstrap.find_by_identifier(identifier)
            if bootstrap:
                deregister_status = RegistrationBootstrapService.deregister_bootstrap(bootstrap)
                delete_status = RegistrationBootstrapService.delete_bootstrap(bootstrap)
                if deregister_status != HTTPStatus.OK or delete_status != HTTPStatus.OK:
                    current_app.logger.error('Unable to deregister and delete temp reg:', identifier)

        return jsonify({'message': _('Filing deleted.')}), HTTPStatus.OK

    @staticmethod
    @cors.crossdomain(origin='*')
    @jwt.requires_auth
    def patch(identifier, filing_id=None):
        """Cancel the payment and resets the filing status to DRAFT."""
        if not filing_id:
            return ({'message':
                     _('No filing id provided for:') + identifier},
                    HTTPStatus.BAD_REQUEST)

        # check authorization
        if not authorized(identifier, jwt, action=['edit']):
            return jsonify({'message':
                            _('You are not authorized to delete a filing for:') + identifier}), \
                HTTPStatus.UNAUTHORIZED

        filing = Business.get_filing_by_id(identifier, filing_id)

        if not filing:
            return jsonify({'message': ('Filing Not Found.')}), \
                HTTPStatus.NOT_FOUND

        try:
            payment_svc_url = '{}/{}'.format(current_app.config.get('PAYMENT_SVC_URL'), filing.payment_token)
            token = jwt.get_token_auth_header()
            headers = {'Authorization': 'Bearer ' + token}
            rv = requests.delete(url=payment_svc_url, headers=headers, timeout=20.0)
            if rv.status_code == HTTPStatus.OK or rv.status_code == HTTPStatus.ACCEPTED:
                filing.reset_filing_to_draft()

        except (exceptions.ConnectionError, exceptions.Timeout) as err:
            current_app.logger.error(f'Payment connection failure for {identifier}: filing:{filing.id}', err)
            return {'errors':
                    [{'message': 'Unable to cancel payment for the filing.'}]
                    }, HTTPStatus.INTERNAL_SERVER_ERROR

        except BusinessException as err:
            return {'errors': [{'message': err.error}]}, err.status_code

        return jsonify(filing.json), HTTPStatus.ACCEPTED

    @staticmethod
    def complete_filing(business, filing, draft) -> Tuple[dict, int]:
        """Complete the filing, either to COLIN or by getting an invoice.

        Used for encapsulation of common functionality used in Filing and Business endpoints.
        """
        # if filing is from COLIN, place on queue and return
        if jwt.validate_roles([COLIN_SVC_ROLE]):
            err_msg, err_code = ListFilingResource._process_colin_filing(business.identifier, filing, business)
            return jsonify(err_msg), err_code

        # create invoice
        if not draft:
            filing_types = ListFilingResource._get_filing_types(filing.filing_json)
            err_msg, err_code = ListFilingResource._create_invoice(business, filing, filing_types, jwt)
            if err_code:
                reply = filing.json
                reply['errors'] = [err_msg, ]
                return jsonify(reply), err_code
            ListFilingResource._set_effective_date(business, filing)

        return None, None

    @staticmethod
    def _put_basic_checks(identifier, filing_id, client_request) -> Tuple[dict, int]:
        """Perform basic checks to ensure put can do something."""
        json_input = client_request.get_json()
        if not json_input:
            return ({'message':
                     f'No filing json data in body of post for {identifier}.'},
                    HTTPStatus.BAD_REQUEST)

        if filing_id and client_request.method != 'PUT':  # checked since we're overlaying routes
            return ({'message':
                     f'Illegal to attempt to create a duplicate filing for {identifier}.'},
                    HTTPStatus.FORBIDDEN)

        return None, None

    @staticmethod
    def _is_before_epoch_filing(filing_json: str, business: Business):
        if not business or not filing_json:
            return False
        epoch_filing = Filing.get_filings_by_status(business_id=business.id, status=[Filing.Status.EPOCH.value])
        if len(epoch_filing) != 1:
            current_app.logger.error('Business:%s either none or too many epoch filings', business.identifier)
            return False
        filing_date = datetime.datetime.fromisoformat(
            filing_json['filing']['header']['date']).replace(tzinfo=datetime.timezone.utc)
        return filing_date < epoch_filing[0].filing_date

    @staticmethod
    def _process_colin_filing(identifier: str, filing: Filing, business: Business) -> Tuple[dict, int]:
        try:
            if not filing.colin_event_ids:
                raise KeyError
            if not ListFilingResource._is_before_epoch_filing(filing.filing_json, business):
                payload = {'filing': {'id': filing.id}}
                queue.publish_json(payload)
            else:
                epoch_filing = Filing.get_filings_by_status(business_id=business.id, status=[Filing.Status.EPOCH.value])
                filing.transaction_id = epoch_filing[0].transaction_id
                filing.set_processed()
                filing.save()
            return {'filing': {'id': filing.id}}, HTTPStatus.CREATED
        except KeyError:
            current_app.logger.error('Business:%s missing filing/header/colinIds, unable to post to queue',
                                     identifier)
            return {'errors': {'message': 'missing filing/header/colinIds'}}, HTTPStatus.BAD_REQUEST
        except Exception as err:  # pylint: disable=broad-except; final catch
            current_app.logger.error('Business:%s unable to post to queue, err=%s', identifier, err)
            return {'errors': {'message': 'unable to publish for post processing'}}, HTTPStatus.BAD_REQUEST

    @staticmethod
    def _save_filing(client_request: LocalProxy,  # pylint: disable=too-many-return-statements,too-many-branches
                     business_identifier: str,
                     user: User,
                     filing_id: int) -> Tuple[Union[Business, RegistrationBootstrap], Filing, dict, int]:
        """Save the filing to the ledger.

        If not successful, a dict of errors is returned.

        Returns: {
            Business: business model object found for the identifier provided
            Filing: filing model object for the submitted filing
            dict: a dict of errors
            int: the HTTPStatus error code

        @TODO refactor to a set of single putpose routines
        }
        """
        json_input = client_request.get_json()
        if not json_input:
            return None, None, {'message':
                                f'No filing json data in body of post for {business_identifier}.'}, \
                HTTPStatus.BAD_REQUEST

        if business_identifier.startswith('T'):
            # bootstrap filing
            bootstrap = RegistrationBootstrap.find_by_identifier(business_identifier)
            business = None
            if not bootstrap:
                return None, None, {'message':
                                    f'{business_identifier} not found'}, HTTPStatus.NOT_FOUND
            if client_request.method == 'PUT':
                rv = db.session.query(Filing). \
                    filter(Filing.temp_reg == business_identifier). \
                    filter(Filing.id == filing_id). \
                    one_or_none()
                if not rv:
                    return None, None, {'message':
                                        f'{business_identifier} no filings found'}, HTTPStatus.NOT_FOUND
                filing = rv
            else:
                filing = Filing()
                filing.temp_reg = bootstrap.identifier
                if not json_input['filing'].get('business'):
                    json_input['filing']['business'] = {}
                json_input['filing']['business']['identifier'] = bootstrap.identifier

        else:
            # regular filing for a business
            business = Business.find_by_identifier(business_identifier)
            if not business:
                return None, None, {'message':
                                    f'{business_identifier} not found'}, HTTPStatus.NOT_FOUND

            if client_request.method == 'PUT':
                rv = db.session.query(Business, Filing). \
                    filter(Business.id == Filing.business_id). \
                    filter(Business.identifier == business_identifier). \
                    filter(Filing.id == filing_id). \
                    one_or_none()
                if not rv:
                    return None, None, {'message':
                                        f'{business_identifier} no filings found'}, HTTPStatus.NOT_FOUND
                filing = rv[1]
            else:
                filing = Filing()
                filing.business_id = business.id

        try:
            filing.submitter_id = user.id
            filing.filing_json = json_input
            if user.username == 'coops-updater-job':
                try:
                    filing.filing_date = datetime.datetime.fromisoformat(filing.filing_json['filing']['header']['date'])
                    for colin_id in filing.filing_json['filing']['header']['colinIds']:
                        colin_event_id = ColinEventId()
                        colin_event_id.colin_event_id = colin_id
                        filing.colin_event_ids.append(colin_event_id)
                except KeyError:
                    current_app.logger.error('Business:%s missing filing/header values, unable to save',
                                             business.identifier)
                    return None, None, {'message': 'missing filing/header values'}, HTTPStatus.BAD_REQUEST
            else:
                filing.filing_date = datetime.datetime.utcnow()

            # for any legal type, set effective date as set in json; otherwise leave as default
            filing.effective_date = \
                datetime.datetime.fromisoformat(filing.filing_json['filing']['header']['effectiveDate']) \
                if filing.filing_json['filing']['header'].get('effectiveDate', None) else datetime.datetime.utcnow()

            filing.save()
        except BusinessException as err:
            return None, None, {'error': err.error}, err.status_code

        return business or bootstrap, filing, None, None

    @staticmethod
    def _validate_filing_json(client_request: LocalProxy) -> Tuple[dict, int]:
        """Assert that the json is a valid filing.

        Returns: {
            dict: a dict, success message or array of errors
            int: the HTTPStatus error code
        }
        """
        valid, err = rsbc_schemas.validate(client_request.get_json(), 'filing')

        if valid:
            return {'message': 'Filing is valid'}, HTTPStatus.OK

        errors = []
        for error in err:
            errors.append({'path': '/'.join(error.path), 'error': error.message})
        return errors, HTTPStatus.BAD_REQUEST

    @staticmethod
    def _get_filing_types(filing_json: dict):
        """Get the filing type fee codes for the filing.

        Returns: {
            list: a list, filing type fee codes in the filing
        }
        """
        filing_types = []
        priority_flag = filing_json['filing']['header'].get('priority', False)
        filing_type = filing_json['filing']['header'].get('name', None)

        for k in filing_json['filing'].keys():
            # check if changeOfDirectors is a free filing
            if k == 'changeOfDirectors':
                free = True
                free_changes = ['nameChanged', 'addressChanged']
                for director in filing_json['filing'][k].get('directors'):
                    # if changes other than name/address change then this is not a free filing
                    if not all(change in free_changes for change in director.get('actions', [])):
                        free = False
                        break
                filing_types.append({
                    'filingTypeCode': 'OTFDR' if free else Filing.FILINGS[k].get('code'),
                    'priority': False if filing_type == 'annualReport' else priority_flag,
                    'waiveFees': filing_json['filing']['header'].get('waiveFees', False)
                })
            elif k == 'changeOfAddress':
                filing_types.append({
                    'filingTypeCode': Filing.FILINGS[k].get('code'),
                    'priority': False if filing_type == 'annualReport' else priority_flag,
                    'waiveFees': filing_json['filing']['header'].get('waiveFees', False)
                })
            elif k == 'incorporationApplication':
                filing_types.append({
                    'filingTypeCode': Filing.FILINGS[k].get('code'),
                    'futureEffective': ListFilingResource._is_future_effective_filing(filing_json)
                })
            elif Filing.FILINGS.get(k, None):
                filing_types.append({
                    'filingTypeCode': Filing.FILINGS[k].get('code'),
                    'priority': priority_flag,
                    'waiveFees': filing_json['filing']['header'].get('waiveFees', False)
                })
        return filing_types

    @staticmethod
    def _create_invoice(business: Business,  # pylint: disable=too-many-locals
                        filing: Filing,
                        filing_types: list,
                        user_jwt: JwtManager) \
            -> Tuple[int, dict, int]:
        """Create the invoice for the filing submission.

        Returns: {
            int: the paymentToken (id), or None
            dict: a dict of errors, or None
            int: the HTTPStatus error code, or None
        }
        """
        payment_svc_url = current_app.config.get('PAYMENT_SVC_URL')

        if filing.filing_type == Filing.FILINGS['incorporationApplication'].get('name'):
            mailing_address = Address.create_address(
                filing.json['filing']['incorporationApplication']['offices']['registeredOffice']['mailingAddress'])
            corp_type = filing.json['filing']['business'].get('legalType', 'BC')

            try:
                business.legal_name = filing.json['filing']['incorporationApplication']['nameRequest']['legalName']
            except KeyError:
                business.legal_name =  business.identifier

        else:
            mailing_address = business.mailing_address.one_or_none()
            corp_type = business.identifier[:-7]

        payload = {
            'businessInfo': {
                'businessIdentifier': f'{business.identifier}',
                'corpType': f'{corp_type}',
                'businessName': f'{business.legal_name}',
                'contactInfo': {'city': mailing_address.city,
                                'postalCode': mailing_address.postal_code,
                                'province': mailing_address.region,
                                'addressLine1': mailing_address.street,
                                'country': mailing_address.country}
            },
            'filingInfo': {
                'filingTypes': filing_types
            }
        }

        folio_number = filing.json['filing']['header'].get('folioNumber', None)
        if folio_number:
            payload['filingInfo']['folioNumber'] = folio_number

        if user_jwt.validate_roles([STAFF_ROLE]):
            routing_slip_number = get_str(filing.filing_json, 'filing/header/routingSlipNumber')
            if routing_slip_number:
                payload['accountInfo'] = {'routingSlip': routing_slip_number}
        try:
            token = user_jwt.get_token_auth_header()
            headers = {'Authorization': 'Bearer ' + token,
                       'Content-Type': 'application/json'}
            rv = requests.post(url=payment_svc_url,
                               json=payload,
                               headers=headers,
                               timeout=20.0)
        except (exceptions.ConnectionError, exceptions.Timeout) as err:
            current_app.logger.error(f'Payment connection failure for {business.identifier}: filing:{filing.id}', err)
            return {'message': 'unable to create invoice for payment.'}, HTTPStatus.PAYMENT_REQUIRED

        if rv.status_code == HTTPStatus.OK or rv.status_code == HTTPStatus.CREATED:
            pid = rv.json().get('id')
            filing.payment_token = pid
            filing.payment_status_code = rv.json().get('statusCode', '')
            filing.save()
            return None, None

        if rv.status_code == HTTPStatus.BAD_REQUEST:
            # Set payment error type used to retrieve error messages from pay-api
            error_type = rv.json().get('type')
            filing.payment_status_code = error_type
            filing.save()

            return {'payment_error_type': error_type,
                    'message': rv.json().get('detail')}, HTTPStatus.PAYMENT_REQUIRED

        return {'message': 'unable to create invoice for payment.'}, HTTPStatus.PAYMENT_REQUIRED

    @staticmethod
    def _set_effective_date(business: Business, filing: Filing):
        filing_type = filing.filing_json['filing']['header']['name']
        if filing_type == Filing.FILINGS['incorporationApplication'].get('name'):
            fe_date = filing.filing_json['filing']['header'].get('futureEffectiveDate')
            if fe_date:
                filing.effective_date = datetime.datetime.fromisoformat(fe_date)
                filing.save()

        elif business.legal_type != 'CP':
            if filing_type == 'changeOfAddress':
                effective_date = LegislationDatetime.tomorrow_midnight()
                filing.filing_json['filing']['header']['futureEffectiveDate'] = effective_date
                filing.effective_date = effective_date
                filing.save()

    @staticmethod
    def _is_future_effective_filing(filing_json: dict) -> bool:
        is_future_effective = False
        effective_date = datetime.datetime.fromisoformat(filing_json['filing']['header']['effectiveDate']) \
            if filing_json['filing']['header'].get('effectiveDate', None) else None
        if effective_date:
            is_future_effective = effective_date > datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)
        return is_future_effective

    @staticmethod
    def _populate_business_info_to_filing(filing: Filing, business: Business):
        founding_datetime = LegislationDatetime.as_legislation_timezone(business.founding_date)
        hour = founding_datetime.strftime('%I')
        business_json = business.json()
        business_json['formatted_founding_date_time'] = \
            founding_datetime.strftime(f'%B %-d, %Y at {hour}:%M %p Pacific Time')
        business_json['formatted_founding_date'] = founding_datetime.strftime('%B %-d, %Y')
        filing.filing_json['filing']['business'] = business_json
        filing.filing_json['filing']['header']['filingId'] = filing.id


@cors_preflight('GET, POST, PUT, PATCH, DELETE')
@API.route('/internal/filings', methods=['GET', 'OPTIONS'])
@API.route('/internal/filings/<string:status>', methods=['GET', 'OPTIONS'])
@API.route('/internal/filings/<int:filing_id>', methods=['PATCH', 'OPTIONS'])
class InternalFilings(Resource):
    """Internal Filings service for cron jobs."""

    @staticmethod
    @cors.crossdomain(origin='*')
    def get(status=None):
        """Get filings by status formatted in json."""
        pending_filings = []
        filings = []

        if status is None:
            pending_filings = Filing.get_completed_filings_for_colin()
            for filing in pending_filings:
                filing_json = filing.filing_json
                if filing_json and filing.filing_type != 'lear_epoch':
                    filing_json['filingId'] = filing.id
                    filings.append(filing_json)
            return jsonify(filings), HTTPStatus.OK

        pending_filings = Filing.get_all_filings_by_status(status)
        for filing in pending_filings:
            filings.append(filing.json)
        return jsonify(filings), HTTPStatus.OK

    @staticmethod
    @cors.crossdomain(origin='*')
    @jwt.requires_auth
    def patch(filing_id):
        """Patch the colin_event_id for a filing."""
        # check authorization
        try:
            if not jwt.validate_roles([COLIN_SVC_ROLE]):
                return jsonify({'message': 'You are not authorized to update the colin id'}), HTTPStatus.UNAUTHORIZED

            json_input = request.get_json()
            if not json_input:
                return None, None, {'message': f'No filing json data in body of patch for {filing_id}.'}, \
                    HTTPStatus.BAD_REQUEST

            colin_ids = json_input['colinIds']
            filing = Filing.find_by_id(filing_id)
            if not filing:
                return {'message': f'{filing_id} no filings found'}, HTTPStatus.NOT_FOUND
            for colin_id in colin_ids:
                try:
                    colin_event_id_obj = ColinEventId()
                    colin_event_id_obj.colin_event_id = colin_id
                    filing.colin_event_ids.append(colin_event_id_obj)
                    filing.save()
                except BusinessException as err:
                    current_app.logger.Error(f'Error adding colin event id {colin_id} to filing with id {filing_id}')
                    return None, None, {'message': err.error}, err.status_code

            return jsonify(filing.json), HTTPStatus.ACCEPTED
        except Exception as err:
            current_app.logger.Error(f'Error patching colin event id for filing with id {filing_id}')
            raise err


@cors_preflight('GET, POST, PUT, PATCH, DELETE')
@API.route('/internal/filings/colin_id', methods=['GET', 'OPTIONS'])
@API.route('/internal/filings/colin_id/<int:colin_id>', methods=['GET', 'POST', 'OPTIONS'])
class ColinLastUpdate(Resource):
    """Endpoints for colin_last_update table."""

    @staticmethod
    @cors.crossdomain(origin='*')
    def get(colin_id=None):
        """Get the last colin id updated in legal."""
        try:
            if colin_id:
                colin_id_obj = ColinEventId.get_by_colin_id(colin_id)
                if not colin_id_obj:
                    return {'message': 'No colin ids found'}, HTTPStatus.NOT_FOUND
                return {'colinId': colin_id_obj.colin_event_id}, HTTPStatus.OK
        except Exception as err:
            current_app.logger.Error(f'Failed to get last updated colin event id: {err}')
            raise err

        query = db.session.execute(
            """
            select last_event_id from colin_last_update
            order by id desc
            """
        )
        last_event_id = query.fetchone()
        if not last_event_id or not last_event_id[0]:
            return {'message': 'No colin ids found'}, HTTPStatus.NOT_FOUND

        return {'maxId': last_event_id[0]}, HTTPStatus.OK if request.method == 'GET' else HTTPStatus.CREATED

    @staticmethod
    @cors.crossdomain(origin='*')
    @jwt.requires_auth
    def post(colin_id):
        """Add a row to the colin_last_update table."""
        try:
            # check authorization
            if not jwt.validate_roles([COLIN_SVC_ROLE]):
                return jsonify({'message': 'You are not authorized to update this table'}), HTTPStatus.UNAUTHORIZED
            db.session.execute(
                f"""
                insert into colin_last_update (last_update, last_event_id)
                values (current_timestamp, {colin_id})
                """
            )
            db.session.commit()
            return ColinLastUpdate.get()

        except Exception as err:  # pylint: disable=broad-except
            current_app.logger.error(f'Error updating colin_last_update table in legal db: {err}')
            return {'message: failed to update colin_last_update.', 500}
