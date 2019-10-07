
import logging
import os.path

from elasticapm.contrib.flask import ElasticAPM
from flask import Flask
from flask.logging import default_handler

from assemblyline_ui.api.base import api
from assemblyline_ui.api.v3 import apiv3
from assemblyline_ui.api.v4 import apiv4
from assemblyline_ui.api.v4.alert import alert_api
from assemblyline_ui.api.v3.authentication import auth_api as auth_v3_api
from assemblyline_ui.api.v4.authentication import auth_api
from assemblyline_ui.api.v4.bundle import bundle_api
from assemblyline_ui.api.v4.error import error_api
from assemblyline_ui.api.v4.file import file_api
from assemblyline_ui.api.v4.hash_search import hash_search_api
from assemblyline_ui.api.v4.help import help_api
from assemblyline_ui.api.v4.heuristics import heuristics_api
from assemblyline_ui.api.v4.ingest import ingest_api
from assemblyline_ui.api.v4.live import live_api
from assemblyline_ui.api.v4.result import result_api
from assemblyline_ui.api.v4.search import search_api
from assemblyline_ui.api.v4.service import service_api
from assemblyline_ui.api.v4.signature import signature_api
from assemblyline_ui.api.v4.submission import submission_api
from assemblyline_ui.api.v4.submit import submit_api
from assemblyline_ui.api.v4.u2f import u2f_api
from assemblyline_ui.api.v4.ui import ui_api
from assemblyline_ui.api.v3.user import user_api as user_v3_api
from assemblyline_ui.api.v4.user import user_api
from assemblyline_ui.api.v4.vm import vm_api
from assemblyline_ui.api.v4.workflow import workflow_api
from assemblyline_ui.error import errors
from assemblyline_ui.views import views

from assemblyline_ui import config
from assemblyline.common import forge

context = forge.get_ui_context()
register_site_specific_routes = context.register_site_specific_routes

##########################
# App settings
current_directory = os.path.dirname(__file__)
app = Flask(
    "assemblyline_ui",
    static_folder=os.path.join(current_directory, 'static'),
    template_folder=os.path.join(current_directory, 'templates'),
)
app.logger.setLevel(60)  # This completely turns off the flask logger
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SECRET_KEY=config.SECRET_KEY,
    PREFERRED_URL_SCHEME='https'
)

app.register_blueprint(api)
app.register_blueprint(apiv3)
app.register_blueprint(apiv4)
app.register_blueprint(auth_api)
app.register_blueprint(auth_v3_api)
app.register_blueprint(alert_api)
app.register_blueprint(bundle_api)
app.register_blueprint(errors)
app.register_blueprint(error_api)
app.register_blueprint(file_api)
app.register_blueprint(hash_search_api)
app.register_blueprint(help_api)
app.register_blueprint(heuristics_api)
app.register_blueprint(ingest_api)
app.register_blueprint(live_api)
app.register_blueprint(result_api)
app.register_blueprint(search_api)
app.register_blueprint(service_api)
app.register_blueprint(signature_api)
app.register_blueprint(submission_api)
app.register_blueprint(submit_api)
app.register_blueprint(u2f_api)
app.register_blueprint(ui_api)
app.register_blueprint(user_api)
app.register_blueprint(user_v3_api)
app.register_blueprint(views)
# app.register_blueprint(vm_api)
app.register_blueprint(workflow_api)

register_site_specific_routes(app)

# Setup logging
app.logger.setLevel(config.LOGGER.getEffectiveLevel())
app.logger.removeHandler(default_handler)
for ph in config.LOGGER.parent.handlers:
    app.logger.addHandler(ph)

# Setup APMs
if config.config.core.metrics.apm_server.server_url is not None:
    app.logger.info(f"Exporting application metrics to: {config.config.core.metrics.apm_server.server_url}")
    ElasticAPM(app, server_url=config.config.core.metrics.apm_server.server_url, service_name="al_ui")


def main():
    wlog = logging.getLogger('werkzeug')
    wlog.setLevel(config.LOGGER.getEffectiveLevel())
    for h in config.LOGGER.parent.handlers:
        wlog.addHandler(h)

    app.jinja_env.cache = {}
    app.run(host="0.0.0.0", debug=False)


if __name__ == '__main__':
    main()