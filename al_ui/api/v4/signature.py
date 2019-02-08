
from flask import request
from hashlib import sha256
from textwrap import dedent

from assemblyline.common import forge
from assemblyline.common.isotime import iso_to_epoch, now_as_iso
from assemblyline.common.yara import YaraParser
from assemblyline.datastore import SearchException
from assemblyline.odm.models.signature import DEPLOYED_STATUSES, STALE_STATUSES, DRAFT_STATUSES
from assemblyline.remote.datatypes.lock import Lock
from al_ui.api.base import api_login, make_api_response, make_file_response, make_subapi_blueprint
from al_ui.config import LOGGER, STORAGE, ORGANISATION


Classification = forge.get_classification()
config = forge.get_config()

SUB_API = 'signature'
signature_api = make_subapi_blueprint(SUB_API, api_version=4)
signature_api._doc = "Perform operations on signatures"


@signature_api.route("/add/", methods=["PUT"])
@api_login(audit=False, required_priv=['W'], allow_readonly=False)
def add_signature(**kwargs):
    """
    Add a signature to the system and assigns it a new ID
        WARNING: If two person call this method at exactly the
                 same time, they might get the same ID.
       
    Variables:
    None
    
    Arguments: 
    None
    
    Data Block (REQUIRED): # Signature block
    {"name": "sig_name",          # Signature name    
     "tags": ["PECheck"],         # Signature tags
     "comments": [""],            # Signature comments lines
     "meta": {                    # Meta fields ( **kwargs )
       "id": "SID",                 # Mandatory ID field
       "rule_version": 1 },         # Mandatory Revision field
     "type": "rule",              # Rule type (rule, private rule ...)
     "strings": ['$ = "a"'],      # Rule string section (LIST)
     "condition": ["1 of them"]}  # Rule condition section (LIST)    
    
    Result example:
    {"success": true,      #If saving the rule was a success or not
     "sid": "0000000000",  #SID that the rule was assigned
     "rev": 2 }            #Revision number at which the rule was saved.
    """
    user = kwargs['user']
    new_id = STORAGE.get_signature_last_id(ORGANISATION) + 1
    new_rev = 1
    data = request.json
    
    if not Classification.is_accessible(user['classification'], data['meta'].get('classification',
                                                                                 Classification.UNRESTRICTED)):
        return make_api_response("", "You are not allowed to add a signature with "
                                     "higher classification than yours", 403)

    if not user['is_admin'] and "global" in data['type']:
        return make_api_response("", "Only admins are allowed to add global signatures.", 403)

    sid = "%s_%06d" % (data['meta']['organisation'], new_id)
    data['meta']['rule_id'] = sid
    data['meta']['rule_version'] = new_rev
    data['meta']['last_saved_by'] = user['uname']
    key = "%sr.%s" % (data['meta']['rule_id'], data['meta']['rule_version'])
    yara_version = data['meta'].get('yara_version', None)
    data['depends'], data['modules'] = \
        YaraParser.parse_dependencies(data['condition'], YaraParser.YARA_MODULES.get(yara_version, None))
    res = YaraParser.validate_rule(data)
    if res['valid']:
        query = "name:{name} AND NOT _yz_rk:{sid}*"
        other = STORAGE.direct_search(
            'signature', query.format(name=data['name'], sid=sid),
            args=[('fl', '_yz_rk'), ('rows', '0')],
        )
        if other.get('response', {}).get('numFound', 0) > 0:
            return make_api_response(
                {"success": False},
                "A signature with that name already exists",
                403
            )
            
        data['warning'] = res.get('warning', None)
        STORAGE.save_signature(key, data)
        return make_api_response({"success": True, "sid": data['meta']['rule_id'], "rev": data['meta']['rule_version']})
    else:
        return make_api_response({"success": False}, res, 403)


# noinspection PyPep8Naming
@signature_api.route("/change_status/<sid>/<rev>/<status>/", methods=["GET"])
@api_login(required_priv=['W'], allow_readonly=False)
def change_status(sid, rev, status, **kwargs):
    """
    [INCOMPLETE]
       - DISABLE OTHER REVISION OF THE SAME SIGNTURE WHEN DEPLOYING ONE
    Change the status of a signature
       
    Variables:
    sid    =>  ID of the signature
    rev    =>  Revision number of the signature
    status  =>  New state
    
    Arguments: 
    None
    
    Data Block:
    None
    
    Result example:
    { "success" : true }      #If saving the rule was a success or not
    """
    user = kwargs['user']
    possible_statuses = DEPLOYED_STATUSES + DRAFT_STATUSES
    if status not in possible_statuses:
        return make_api_response("",
                                 f"You cannot apply the status {status} on yara rules.",
                                 403)
    if not user['is_admin'] and status in DEPLOYED_STATUSES:
        return make_api_response("",
                                 "Only admins are allowed to change the signature status to a deployed status.",
                                 403)
    
    key = f"{sid}r.{rev}"
    data = STORAGE.signature.get(key, as_obj=False)
    if data:
        if not Classification.is_accessible(user['classification'], data['meta'].get('classification',
                                                                                     Classification.UNRESTRICTED)):
            return make_api_response("", "You are not allowed change status on this signature", 403)
    
        if data['meta']['al_status'] in STALE_STATUSES and status not in DRAFT_STATUSES:
            return make_api_response("",
                                     f"Only action available while signature in {data['meta']['al_status']} "
                                     f"status is to change signature to a DRAFT status. ({', '.join(DRAFT_STATUSES)})",
                                     403)

        if data['meta']['al_status'] in DEPLOYED_STATUSES and status in DRAFT_STATUSES:
            return make_api_response("",
                                     f"You cannot change the status of signature {sid} r.{rev} from "
                                     f"{data['meta']['al_status']} to {status}.", 403)

        query = "meta.al_status:{status} AND id:{sid}* AND NOT id:{key}"
        today = now_as_iso()
        uname = user['uname']

        if status not in ['DISABLED', 'INVALID', 'TESTING']:
            keys = [k['id']
                    for k in STORAGE.signature.search(query.format(key=key, sid=sid, status=status),
                                                      fl="id", as_obj=False)['items']]
            for other in STORAGE.signature.multiget(keys, as_obj=False):
                other['meta_extra']['al_state_change_date'] = today
                other['meta_extra']['al_state_change_user'] = uname
                other['meta']['al_status'] = 'DISABLED'

                other_sid = other['meta']['rule_id']
                other_rev = other['meta']['rule_version']
                other_key = "%sr.%s" % (other_sid, other_rev)
                STORAGE.save_signature(other_key, other)

        data['meta_extra']['al_state_change_date'] = today
        data['meta_extra']['al_state_change_user'] = uname
        data['meta']['al_status'] = status

        return make_api_response({"success": STORAGE.signature.save(key, data)})
    else:
        return make_api_response("", "Signature not found. (%s r.%s)" % (sid, rev), 404)


@signature_api.route("/<sid>/<rev>/", methods=["DELETE"])
@api_login(required_priv=['W'], allow_readonly=False, require_admin=True)
def delete_signature(sid, rev, **kwargs):
    """
    Delete a signature based of its ID and revision

    Variables:
    sid    =>     Signature ID
    rev    =>     Signature revision number

    Arguments:
    None

    Data Block:
    None

    Result example:
    {"success": True}  # Signature delete successful
    """
    user = kwargs['user']
    data = STORAGE.signature.get(f"{sid}r.{rev}", as_obj=False)
    if data:
        if not Classification.is_accessible(user['classification'],
                                            data['meta'].get('classification', Classification.UNRESTRICTED)):
            return make_api_response("", "Your are not allowed to delete this signature.", 403)
        return make_api_response({"success": STORAGE.signature.delete(f"{sid}r.{rev}")})
    else:
        return make_api_response("", f"Signature not found. ({sid} r.{rev})", 404)


# noinspection PyBroadException
def _get_cached_signatures(signature_cache, query_hash):
    try:
        s = signature_cache.get(query_hash)
        if s is None:
            return s
        return make_file_response(
            s, f"al_yara_signatures_{query_hash[:7]}.yar", len(s), content_type="text/yara"
        )
    except Exception:  # pylint: disable=W0702
        LOGGER.exception('Failed to read cached signatures:')

    return None


@signature_api.route("/download/", methods=["GET"])
@api_login(required_priv=['R'], check_xsrf_token=False, allow_readonly=False)
def download_signatures(**kwargs):
    """
    Download signatures from the system.
    
    Variables:
    None 
    
    Arguments: 
    query       => SOLR query to filter the signatures
                   Default: All deployed signatures
    safe        => Get a ruleset that will work in yara
                   Default: False
    
    Data Block:
    None
    
    Result example:
    <A .YAR SIGNATURE FILE>
    """
    user = kwargs['user']
    query = request.args.get('query', 'meta.al_status:DEPLOYED')
    safe = request.args.get('safe', "false") == 'true'

    access = user['access_control']
    last_modified = STORAGE.get_signature_last_modified()

    query_hash = sha256(f'{query}.{access}.{last_modified}'.encode('utf-8')).hexdigest()

    with forge.get_cachestore() as signature_cache:
        response = _get_cached_signatures(signature_cache, query_hash)
        if response:
            return response

        with Lock(f"{query_hash}.yar", 30):
            response = _get_cached_signatures(signature_cache, query_hash)
            if response:
                return response

            keys = [k['id']
                    for k in STORAGE.signature.search(query, fl="id", access_control=access, as_obj=False)['items']]
            signature_list = STORAGE.signature.multiget(keys, as_dictionary=False, as_obj=False)

            # Sort rules to satisfy dependencies
            duplicate_rules = []
            error_rules = []
            global_rules = []
            private_rules_no_dep = []
            private_rules_dep = []
            rules_no_dep = []
            rules_dep = []

            if safe:
                rules_map = {}
                for s in signature_list:
                    name = s.get('name', None)
                    if not name:
                        continue

                    version = int(s.get('meta', {}).get('rule_version', '1'))

                    p = rules_map.get(name, {})
                    pversion = int(p.get('meta', {}).get('rule_version', '0'))

                    if version < pversion:
                        duplicate_rules.append(name)
                        continue

                    rules_map[name] = s
                signature_list = rules_map.values()

            name_map = {}
            for s in signature_list:
                if s['type'].startswith("global"):
                    global_rules.append(s)
                    name_map[s['name']] = True
                elif s['type'].startswith("private"):
                    if s['depends'] is None or len(s['depends']) == 0:
                        private_rules_no_dep.append(s)
                        name_map[s['name']] = True
                    else:
                        private_rules_dep.append(s)
                else:
                    if s['depends'] is None or len(s['depends']) == 0:
                        rules_no_dep.append(s)
                        name_map[s['name']] = True
                    else:
                        rules_dep.append(s)

            global_rules = sorted(global_rules, key=lambda k: k['meta']['rule_id'])
            private_rules_no_dep = sorted(private_rules_no_dep, key=lambda k: k['meta']['rule_id'])
            rules_no_dep = sorted(rules_no_dep, key=lambda k: k['meta']['rule_id'])
            private_rules_dep = sorted(private_rules_dep, key=lambda k: k['meta']['rule_id'])
            rules_dep = sorted(rules_dep, key=lambda k: k['meta']['rule_id'])

            signature_list = global_rules + private_rules_no_dep
            while private_rules_dep:
                new_private_rules_dep = []
                for r in private_rules_dep:
                    found = False
                    for d in r['depends']:
                        if not name_map.get(d, False):
                            new_private_rules_dep.append(r)
                            found = True
                            break
                    if not found:
                        name_map[r['name']] = True
                        signature_list.append(r)

                if private_rules_dep == new_private_rules_dep:
                    for x in private_rules_dep:
                        error_rules += [d for d in x["depends"]]

                    if not safe:
                        for s in private_rules_dep:
                            name_map[s['name']] = True
                        signature_list += private_rules_dep

                    new_private_rules_dep = []

                private_rules_dep = new_private_rules_dep

            signature_list += rules_no_dep
            while rules_dep:
                new_rules_dep = []
                for r in rules_dep:
                    found = False
                    for d in r['depends']:
                        if not name_map.get(d, False):
                            new_rules_dep.append(r)
                            found = True
                            break
                    if not found:
                        name_map[r['name']] = True
                        signature_list.append(r)

                if rules_dep == new_rules_dep:
                    error_rules += [x["name"] for x in rules_dep]
                    if not safe:
                        for s in rules_dep:
                            name_map[s['name']] = True
                        signature_list += rules_dep

                    new_rules_dep = []

                rules_dep = new_rules_dep
            # End of sort

            error = ""
            if duplicate_rules:
                if safe:
                    err_txt = "were skipped"
                else:
                    err_txt = "exist"
                error += dedent("""\
                
                    // [ERROR] Duplicates rules {msg}:
                    //
                    //	{rules}
                    //
                    """).format(msg=err_txt, rules="\n//\t".join(duplicate_rules))
            if error_rules:
                if safe:
                    err_txt = "were skipped due to"
                else:
                    err_txt = "are"
                error += dedent("""\
                
                    // [ERROR] Some rules {msg} missing dependencies:
                    //
                    //	{rules}
                    //
                    """).format(msg=err_txt, rules="\n//\t".join(error_rules))
            # noinspection PyAugmentAssignment

            header = dedent("""\
                // Signatures last updated: {last_modified}
                // Yara file unique identifier: {query_hash}
                // Query executed to find signatures:
                //
                //	{query}
                // {error}
                // Number of rules in file:
                //
                """).format(query=query, error=error, last_modified=last_modified, query_hash=query_hash)

            rule_file_bin = header + YaraParser().dump_rule_file(signature_list)
            rule_file_bin = rule_file_bin

            signature_cache.save(query_hash, rule_file_bin)

            return make_file_response(
                rule_file_bin, f"al_yara_signatures_{query_hash[:7]}.yar",
                len(rule_file_bin), content_type="text/yara"
            )


@signature_api.route("/<sid>/<rev>/", methods=["GET"])
@api_login(required_priv=['R'], allow_readonly=False)
def get_signature(sid, rev, **kwargs):
    """
    Get the detail of a signature based of its ID and revision
    
    Variables:
    sid    =>     Signature ID
    rev    =>     Signature revision number
    
    Arguments: 
    None
    
    Data Block:
    None
     
    Result example:
    {"name": "sig_name",          # Signature name    
     "tags": ["PECheck"],         # Signature tags
     "comments": [""],            # Signature comments lines
     "meta": {                    # Meta fields ( **kwargs )
       "id": "SID",                 # Mandatory ID field
       "rule_version": 1 },         # Mandatory Revision field
     "type": "rule",              # Rule type (rule, private rule ...)
     "strings": ['$ = "a"'],      # Rule string section (LIST)
     "condition": ["1 of them"]}  # Rule condition section (LIST)    
    """
    user = kwargs['user']
    data = STORAGE.signature.get(f"{sid}r.{rev}", as_obj=False)
    if data:
        if not Classification.is_accessible(user['classification'],
                                            data['meta'].get('classification',
                                                             Classification.UNRESTRICTED)):
            return make_api_response("", "Your are not allowed to view this signature.", 403)
        return make_api_response(data)
    else:
        return make_api_response("", "Signature not found. (%s r.%s)" % (sid, rev), 404)


@signature_api.route("/list/", methods=["GET"])
@api_login(required_priv=['R'], allow_readonly=False)
def list_signatures(**kwargs):
    """
    List all the signatures in the system. 
    
    Variables:
    None 
    
    Arguments: 
    offset       => Offset at which we start giving signatures
    rows         => Numbers of signatures to return
    query        => Filter to apply on the signature list
    
    Data Block:
    None
    
    Result example:
    {"total": 201,                # Total signatures found
     "offset": 0,                 # Offset in the signature list
     "count": 100,                # Number of signatures returned
     "items": [{                  # List of Signatures:
       "name": "sig_name",          # Signature name    
       "tags": ["PECheck"],         # Signature tags
       "comments": [""],            # Signature comments lines
       "meta": {                    # Meta fields ( **kwargs )
         "id": "SID",                 # Mandatory ID field
         "rule_version": 1 },         # Mandatory Revision field
       "type": "rule",              # Rule type (rule, private rule ...)
       "strings": ['$ = "a"'],      # Rule string section (LIST)
       "condition": ["1 of them"]   # Rule condition section (LIST)
       }, ... ]}
    """
    user = kwargs['user']
    offset = int(request.args.get('offset', 0))
    rows = int(request.args.get('rows', 100))
    query = request.args.get('query', "id:*")

    try:
        return make_api_response(STORAGE.signature.search(query, offset=offset, rows=rows,
                                                          access_control=user['access_control'], as_obj=False))
    except SearchException as e:
        return make_api_response("", f"SearchException: {e}", 400)


@signature_api.route("/<sid>/<rev>/", methods=["POST"])
@api_login(required_priv=['W'], allow_readonly=False)
def set_signature(sid, rev, **kwargs):
    """
    [INCOMPLETE]
       - CHECK IF SIGNATURE NAME ALREADY EXISTS
    Update a signature defined by a sid and a rev.
       NOTE: The API will compare they old signature
             with the new one and will make the decision
             to increment the revision number or not. 
    
    Variables:
    sid    =>     Signature ID
    rev    =>     Signature revision number
    
    Arguments: 
    None
    
    Data Block (REQUIRED): # Signature block
    {"name": "sig_name",          # Signature name    
     "tags": ["PECheck"],         # Signature tags
     "comments": [""],            # Signature comments lines
     "meta": {                    # Meta fields ( **kwargs )
       "id": "SID",                 # Mandatory ID field
       "rule_version": 1 },         # Mandatory Revision field
     "type": "rule",              # Rule type (rule, private rule ...)
     "strings": ['$ = "a"'],      # Rule string section (LIST)
     "condition": ["1 of them"]}  # Rule condition section (LIST)    
    
    Result example:
    {"success": true,      #If saving the rule was a success or not
     "sid": "0000000000",  #SID that the rule was assigned (Same as provided)
     "rev": 2 }            #Revision number at which the rule was saved.
    """
    user = kwargs['user']
    key = "%sr.%s" % (sid, rev)
    
    old_data = STORAGE.get_signature(key)
    if old_data:
        data = request.json
        if not Classification.is_accessible(user['classification'],
                                            data['meta'].get('classification',
                                                             Classification.UNRESTRICTED)):
            return make_api_response("", "You are not allowed to change a signature to an "
                                         "higher classification than yours", 403)
    
        if old_data['meta']['al_status'] != data['meta']['al_status']:
            return make_api_response({"success": False}, "You cannot change the signature "
                                                         "status through this API.", 403)
        
        if not Classification.is_accessible(user['classification'],
                                            old_data['meta'].get('classification',
                                                                 Classification.UNRESTRICTED)):
            return make_api_response("", "You are not allowed to change a signature with "
                                         "higher classification than yours", 403)

        if not user['is_admin'] and "global" in data['type']:
            return make_api_response("", "Only admins are allowed to add global signatures.", 403)

        if YaraParser.require_bump(data, old_data):
            data['meta']['rule_version'] = STORAGE.get_last_rev_for_id(sid) + 1
            if 'creation_date' in data['meta']:
                del(data['meta']['creation_date'])
            if 'al_state_change_date' in data['meta']:
                del(data['meta']['al_state_change_date'])
            if 'al_state_change_user' in data['meta']:
                del(data['meta']['al_state_change_user'])
            data['meta']['al_status'] = "TESTING"
            key = "%sr.%s" % (sid, data['meta']['rule_version'])
                
        if 'last_modified' in data['meta']:
            del (data['meta']['last_modified'])
        
        data['meta']['last_saved_by'] = user['uname']
        yara_version = data['meta'].get('yara_version', None)
        data['depends'], data['modules'] = \
            YaraParser.parse_dependencies(data['condition'], YaraParser.YARA_MODULES.get(yara_version, None))
        res = YaraParser.validate_rule(data)
        if res['valid']:
            data['warning'] = res.get('warning', None)
            STORAGE.save_signature(key, data)
            return make_api_response({"success": True,
                                      "sid": data['meta']['rule_id'],
                                      "rev": data['meta']['rule_version']})
        else:
            return make_api_response({"success": False}, res, 403)
    else:
        return make_api_response({"success": False}, "Signature not found. %s" % key, 404)


@signature_api.route("/stats/", methods=["GET"])
@api_login(allow_readonly=False)
def signature_statistics(**kwargs):
    """
    Gather all signatures stats in system

    Variables:
    None

    Arguments:
    None

    Data Block:
    None

    Result example:
    {"total": 201,                # Total heuristics found
     "timestamp":                 # Timestamp of last signatures stats
     "items":                     # List of Signatures
     [{"id": "ORG_000000",           # Signature ID
       "name": "Signature Name"      # Signature name
       "count": "100",               # Count of times signatures seen
       "min": 0,                     # Lowest score found
       "avg": 172,                   # Average of all scores
       "max": 780,                   # Highest score found
     },
     ...
    """
    user = kwargs['user']
    output = {"total": 0, "items": [], "timestamp": None}

    sig_blob = STORAGE.get_blob("signature_stats")

    if sig_blob:
        cleared = []
        try:
            for k, v in sig_blob["stats"].iteritems():
                sig_id, rev = k.rsplit("r.", 1)
                if user and Classification.is_accessible(user['classification'], v[1]):
                    cleared.append({
                        "id": sig_id,
                        "rev": rev,
                        "name": v[0],
                        "count": v[2],
                        "min": v[3],
                        "avg": int(v[4]),
                        "max": v[5],
                        "classification": v[1]
                    })
        except AttributeError:
            pass

        output["items"] = cleared
        output["total"] = len(cleared)
        output["timestamp"] = sig_blob["timestamp"]

    return make_api_response(output)


@signature_api.route("/update_available/", methods=["GET"])
@api_login(required_priv=['R'], allow_readonly=False)
def update_available(**_):
    """
    Check if updated signatures are.

    Variables:
    None

    Arguments:
    last_update        => Epoch time of last update.

    Data Block:
    None

    Result example:
    { "update_available" : true }      # If updated rules are available.
    """
    last_update = iso_to_epoch(request.args.get('last_update', '1970-01-01T00:00:00.000000Z'))
    last_modified = iso_to_epoch(STORAGE.get_signature_last_modified())

    return make_api_response({"update_available": last_modified > last_update})
