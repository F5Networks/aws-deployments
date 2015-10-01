import re
import json
import colander
from pyramid.view import view_config
from deform import Form, ValidationFailure, widget
from pyramid.httpexceptions import HTTPFound

import f5_aws
import f5_aws.runner as runner
from f5_aws.config import Config
from f5_aws.job_manager import JobManager


def check_env_name(value):
    if not value or not re.match("^[a-zA-z]{1}[a-zA-Z0-9-]*", value):
        return False
    return True

def make_pretty(value):
    return value.replace("-", " ").replace("_"," ").upper()

@view_config(route_name="home", renderer="service_catalog:templates/home.jinja2")
def home_view(request):
    return {"project": "service_catalog"}

@view_config(route_name="new_app", renderer="service_catalog:templates/new_app.jinja2")
def new_app_view(request):
    """
    View will allow a post method for which will create
    a new environment.  We use 'deform', a technology for form
    rendering and validation. 
    """
    
    #build the form
    config = Config().config
    aws_region_values = [(i, make_pretty(i)) for i in config["regions"]]
    deployment_model_values = [(i, make_pretty(i)) for i in config["deployment_models"]]
    deployment_type_values = [(i, make_pretty(i)) for i in config["deployment_types"]]
    container_id_values = [(i, make_pretty(i)) for i in config["available_apps"]]

    class AppDeployment(colander.MappingSchema):
        env_name = colander.SchemaNode(colander.String(),
                       title="Deployment Name",
                       validator=colander.Function(check_env_name)
        )
        region = colander.SchemaNode(colander.String(),
                       title="AWS Region",
                       widget = widget.SelectWidget(values=aws_region_values),
                       validator = colander.OneOf(config["regions"])
        )
        container_id = colander.SchemaNode(colander.String(),
                       title="Container ID", 
                       widget = widget.SelectWidget(values=container_id_values),
                       validator = colander.OneOf(config["available_apps"])
        )
        deployment_type = colander.SchemaNode(colander.String(),
                       title="Deployment Type", 
                       widget = widget.SelectWidget(values=deployment_type_values),
                       validator = colander.OneOf(config["deployment_types"])
        )
        deployment_model = colander.SchemaNode(colander.String(),
                       title="Deployment Footprint", 
                       widget = widget.SelectWidget(values=deployment_model_values),
                       validator = colander.OneOf(config["deployment_models"])
        )

    class Schema(colander.MappingSchema):
        app_deployment = AppDeployment()

    schema = Schema()

    # by default, or form submit button posts to this page
    form = Form(schema, buttons=("submit",))

    # include the required headers for our form view
    #  in all structs sent to the renderers
    resources = form.get_widget_resources()
    js_resources = resources["js"]
    css_resources = resources["css"]
    js_links = [ "/static/%s" % r for r in js_resources ]
    css_links = [ "/static/%s" % r for r in css_resources ]
    js_tags = ["<script type="text/javascript" src="%s"></script>" % link
               for link in js_links]
    css_tags = ["<link rel="stylesheet" href="%s"/>" % link
               for link in css_links]
    tags = "\n".join(js_tags + css_tags)

    # If we got a post, someone submitted the form.  Render 
    #  the page based on whether we recieved good inputs.
    if "submit" in request.POST:
        controls = request.POST.items()
        try:
            appstruct = form.validate(controls) 
            inputs = appstruct["app_deployment"]
            
            # initialize this environment and redirect
            # to the deployemnts page if successful
            em = runner.EnvironmentManagerFactory(
                cmd="init",
                env_name=inputs["env_name"],
                extra_vars=
                    {
                        "deployment_model": inputs['deployment_model'],
                        "region": inputs['region'],
                        "zone": (inputs['region'] + 'b'),
                        "image_id": inputs['container_id']
                    }
            )
            result = em.init()
            if (result["playbook_results"] and
                result["playbook_results"].statuscode == 0):

                # submit a job to provision this environment
                jm = JobManager()
                em = runner.EnvironmentManagerFactory(
                    cmd="deploy",
                    env_name=inputs["env_name"] 
                )
                jm.submit_request(em.deploy)
                
                # redirect
                return HTTPFound(location="/myapps")

        except ValidationFailure as e:
            # form validation failed
            # re-render the form with an exception
            return {
                "project": "service_catalog",
                "form": e.render(),
                "tags": tags
            } 

        except Exception as e:
            import traceback
            import sys
            # generic error, show errors
            return {
                "project": "service_catalog",
                "errors": [str(e), traceback.format_exc(), sys.exc_info()[0]],
                "tags": tags
            }

    # base case - render the form
    return {"project": "service_catalog",
            "form": form.render(),
            "tags": tags}

@view_config(route_name="my_apps", renderer="service_catalog:templates/my_apps.jinja2")
def my_apps_view(request):
    """
    View will allow a post method for which will create
    a new environment.  We use 'deform', a technology for form
    rendering and validation. 
    """

    # get a list of the environments
    envs = []
    names = runner.EnvironmentManager.get_envs()
    jm = JobManager()

    for name in names:
        em = runner.EnvironmentManagerFactory(env_name=name, cmd="info")
        inventory, resources, statuses = em.get_environment_info()
        env_info = em.get_env_info(inventory)
        login_info = em.login_info()

        provisioning_status = "deployed"
        for k, v in statuses.iteritems():
            if v != "deployed":
                provisioning_status = "not deployed/error"

        status = jm.get_request_status(name)

        envs.append({
            "name": name,
            "last_msg": status["msg"],
            "env_info": env_info,
            "inventory": inventory,
            "resources": resources,
            "statuses": statuses,
            "login_info": login_info
        })

    #  and the the corrosponding inventories, resources, and login information
    # pass this as a python dictionary to the my_apps template
    # the html page we return should provide the ability to 
    # 1) select whether or not WAF is deployed
    # 2) "redeploy" an architecture 
    # 3) teardown the architecture
    # 4) delete deployment 

    return {"project": "service_catalog", "envs": envs, "request": request}