
from flask import request

from assemblyline.common import forge
from al_ui.api.base import api_login, make_api_response, make_subapi_blueprint
from al_ui.config import STORAGE
from assemblyline.datastore import SearchException

config = forge.get_config()

SUB_API = 'service'
service_api = make_subapi_blueprint(SUB_API, api_version=4)
service_api._doc = "Manage the different services"


@service_api.route("/<servicename>/", methods=["PUT"])
@api_login(require_admin=True, allow_readonly=False)
def add_service(servicename, **_):
    """
    Add a service configuration
    
    Variables: 
    servicename    => Name of the service to add
    
    Arguments: 
    None
    
    Data Block:
    {'accepts': '(archive|executable|java|android)/.*',
     'category': 'Extraction',
     'classpath': 'al_services.alsvc_extract.Extract',
     'config': {'DEFAULT_PW_LIST': ['password', 'infected']},
     'cpu_cores': 0.1,
     'description': "Extracts some stuff"
     'enabled': True,
     'install_by_default': True,
     'name': 'Extract',
     'ram_mb': 256,
     'rejects': 'empty|metadata/.*',
     'stage': 'EXTRACT',
     'submission_params': [{'default': u'',
       'name': 'password',
       'type': 'str',
       'value': u''},
      {'default': False,
       'name': 'extract_pe_sections',
       'type': 'bool',
       'value': False},
      {'default': False,
       'name': 'continue_after_extract',
       'type': 'bool',
       'value': False}],
     'supported_platforms': ['Linux'],
     'timeout': 60}
    
    Result example:
    {"success": true }    #Saving the user info succeded
    """
    data = request.json
    
    if not STORAGE.service.get(servicename):
        return make_api_response({"success": STORAGE.service.save(servicename, data)})
    else:
        return make_api_response({"success": False}, "You cannot add a service that already exists...", 400)


@service_api.route("/constants/", methods=["GET"])
@api_login(audit=False, required_priv=['R'], allow_readonly=False)
def get_service_constants(**_):
    """
    Get global service constants.
    
    Variables: 
    None
    
    Arguments: 
    None
    
    Data Block:
    None
    
    Result example:
    {
        "categories": [
          "Antivirus", 
          "Extraction", 
          "Static Analysis", 
          "Dynamic Analysis"
        ], 
        "stages": [
          "FILTER", 
          "EXTRACT", 
          "SECONDARY", 
          "TEARDOWN"
        ]
    }
    """
    return make_api_response({
        'stages': config.services.stages,
        'categories': config.services.categories,
    })


@service_api.route("/<servicename>/", methods=["GET"])
@api_login(require_admin=True, audit=False, allow_readonly=False)
def get_service(servicename, **_):
    """
    Load the configuration for a given service
    
    Variables: 
    servicename       => Name of the service to get the info
    
    Arguments:
    None
    
    Data Block:
    None
    
    Result example:
    {'accepts': '(archive|executable|java|android)/.*',
     'category': 'Extraction',
     'classpath': 'al_services.alsvc_extract.Extract',
     'config': {'DEFAULT_PW_LIST': ['password', 'infected']},
     'cpu_cores': 0.1,
     'description': "Extracts some stuff"
     'enabled': True,
     'install_by_default': True,
     'name': 'Extract',
     'ram_mb': 256,
     'rejects': 'empty|metadata/.*',
     'stage': 'EXTRACT',
     'submission_params': [{'default': u'',
       'name': 'password',
       'type': 'str',
       'value': u''},
      {'default': False,
       'name': 'extract_pe_sections',
       'type': 'bool',
       'value': False},
      {'default': False,
       'name': 'continue_after_extract',
       'type': 'bool',
       'value': False}],
     'supported_platforms': ['Linux'],
     'timeout': 60}
    """
    service = STORAGE.service.get(servicename, as_obj=False)
    if service:
        return make_api_response(service)
    else:
        return make_api_response("", err=f"{servicename} service does not exist", status_code=404)


@service_api.route("/list/", methods=["GET"])
@api_login(require_admin=True, audit=False, required_priv=['R'], allow_readonly=False)
def list_services(**_):
    """
    List the different service of the system.
    
    Variables:
    offset       => Offset at which we start giving services
    query        => Query to apply on the virtual machines list
    rows         => Numbers of services to return

    Arguments: 
    None
    
    Data Block:
    None
    
    Result example:
     [
        {'accepts': ".*"
         'category': 'Extraction',
         'classpath': 'al_services.alsvc_extract.Extract',
         'description': "Extracts some stuff",
         'enabled': True,
         'name': 'Extract',
         'rejects': 'empty'
         'stage': 'CORE'
         },
         ...
     ]
    """
    offset = int(request.args.get('offset', 0))
    rows = int(request.args.get('rows', 100))
    query = request.args.get('query', "id:*")

    try:
        return make_api_response(STORAGE.service.search(query, offset=offset, rows=rows, as_obj=False))
    except SearchException as e:
        return make_api_response("", f"SearchException: {e}", 400)


@service_api.route("/all/", methods=["GET"])
@api_login(audit=False, required_priv=['R'], allow_readonly=False)
def list_all_services(**_):
    """
    List all service configurations of the system.

    Variables:
    None

    Arguments:
    None

    Data Block:
    None

    Result example:
     [
        {'accepts': ".*"
         'category': 'Extraction',
         'classpath': 'al_services.alsvc_extract.Extract',
         'description': "Extracts some stuff",
         'enabled': True,
         'name': 'Extract',
         'rejects': 'empty'
         'stage': 'CORE'
         },
         ...
     ]
    """
    return make_api_response(STORAGE.list_all_services(as_obj=False))


@service_api.route("/<servicename>/", methods=["DELETE"])
@api_login(require_admin=True, allow_readonly=False)
def remove_service(servicename, **_):
    """
    Remove a service configuration
    
    Variables: 
    servicename       => Name of the service to remove
    
    Arguments:
    None
    
    Data Block:
    None
    
    Result example:
    {"success": true}  # Has the deletion succeeded
    """
    svc = STORAGE.service.get(servicename)
    if svc:
        return make_api_response({"success": STORAGE.service.delete(servicename)})
    else:
        return make_api_response({"success": False},
                                 err=f"Service {servicename} does not exist",
                                 status_code=404)


@service_api.route("/<servicename>/", methods=["POST"])
@api_login(require_admin=True, allow_readonly=False)
def set_service(servicename, **_):
    """
    Save the configuration of a given service
    
    Variables: 
    servicename    => Name of the service to save
    
    Arguments: 
    None
    
    Data Block:
    {'accepts': '(archive|executable|java|android)/.*',
     'category': 'Extraction',
     'classpath': 'al_services.alsvc_extract.Extract',
     'config': {'DEFAULT_PW_LIST': ['password', 'infected']},
     'cpu_cores': 0.1,
     'description': "Extract some stuff",
     'enabled': True,
     'install_by_default': True,
     'name': 'Extract',
     'ram_mb': 256,
     'rejects': 'empty|metadata/.*',
     'stage': 'EXTRACT',
     'submission_params': [{'default': u'',
       'name': 'password',
       'type': 'str',
       'value': u''},
      {'default': False,
       'name': 'extract_pe_sections',
       'type': 'bool',
       'value': False},
      {'default': False,
       'name': 'continue_after_extract',
       'type': 'bool',
       'value': False}],
     'supported_platforms': ['Linux'],
     'timeout': 60}
    
    Result example:
    {"success": true }    #Saving the user info succeded
    """
    data = request.json
    current_service = STORAGE.service.get(servicename, as_obj=False)

    if not current_service:
        return make_api_response({"success": False}, "The service you are trying to modify does not exist", 404)

    if 'name' in data and servicename != data['name']:
        return make_api_response({"success": False}, "You cannot change the service name", 400)

    current_service.update(data)

    return make_api_response({"success": STORAGE.service.save(servicename, current_service)})