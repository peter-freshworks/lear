export class Flow {
  feeCode: string
  displayName: string
  certifyText: string
}

export class Business {
  typeEnum: string
  displayName: string
  flows: Array<Flow>
}

export const configJson = [{
  typeEnum: 'BC',
  displayName: 'Benefit Company',
  flows: [
    {
      feeCode: 'OTADD',
      displayName: 'Change Of Address',
      certifyText: 'Note: It is an offence to make a false or misleading statement in ' +
           'respect of a material fact in a record submitted to the Corporate Registry for filing. ' +
           'See sections 35 and 36 of the Business Corporations Act.'
    },
    {
      feeCode: 'OTANN',
      displayName: 'Annual Report',
      certifyText: 'Note: It is an offence to make a false or misleading statement in ' +
           'respect of a material fact in a record submitted to the Corporate Registry for filing. ' +
           'See section 51 of the Business Corporations Act.'
    },
    {
      feeCode: 'OTCDR',
      displayName: 'Change Of Directors',
      certifyText: 'Note: It is an offence to make a false or misleading statement in ' +
           'respect of a material fact in a record submitted to the Corporate Registry for filing. ' +
           'See section 127 of the Business Corporations Act.',
      warnings: {
        minDirectors: {
          title: 'One Director Required',
          message: 'A minimum of one director is required, to be in compliance with the' +
            'Business Corporations Act (Section xx). You can continue your filing, but you must' +
            'become compliant with the  Business Corporations Act. as soon as possible.'
        },
        bcResident: null,
        canadianResident: null,
        multiCompliance: null
      }
    }
  ]
},
{
  typeEnum: 'CP',
  displayName: 'Cooperative',
  flows: [
    {
      feeCode: 'OTADD',
      displayName: 'Change Of Address',
      certifyText: 'Note: It is an offence to make a false or misleading statement in ' +
           'respect of a material fact in a record submitted to the Corporate Registry for filing. ' +
           'See section 27 of the Cooperative Association Act.'
    },
    {
      feeCode: 'OTANN',
      displayName: 'Annual Report',
      certifyText: 'Note: It is an offence to make a false or misleading statement in ' +
           'respect of a material fact in a record submitted to the Corporate Registry for filing. ' +
           'See section 126 of the Cooperative Association Act.'
    },
    {
      feeCode: 'OTCDR',
      displayName: 'Change Of Directors',
      certifyText: 'Note: It is an offence to make a false or misleading statement in ' +
           'respect of a material fact in a record submitted to the Corporate Registry for filing. ' +
<<<<<<< HEAD
           'See section 78 of the Cooperative Association Act.'
=======
           'See section 78 of the Cooperative Associations Act.',
      warnings: {
        minDirectors: {
          title: 'Minimum Three Directors Required',
          message: 'A minimum of three directors are required, to be in compliance with the Cooperative ' +
            'Association Act (Section xx). You can continue your filing, but you must become compliant ' +
            'with the Cooperative Association Act as soon as possible.'
        },
        bcResident: {
          title: 'BC Resident Director Required',
          message: 'One of the directors of the association is required to be an ' +
            'individual ordinarily resident in British Columbia, to be in compliance ' +
            'with the Cooperative Association Act (Section xx). You can continue your filing, ' +
            'but you must become compliant with the Cooperative Association Act as soon as possible.'
        },
        canadianResident: {
          title: 'Canadian Resident Directors Required',
          message: 'A majority of the directors of the association are required to be individuals ordinarily ' +
            'resident in Canada, to be in compliance with the Cooperative Association Act (Section xx). ' +
            'You can continue your filing, but you must become compliant with the Cooperative ' +
            'Association Act as soon as possible.'
        },
        multiCompliance: {
        }
      }
>>>>>>> new component
    }
  ]
}]
