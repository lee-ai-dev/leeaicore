from django.apps import apps as django_apps
from django.contrib import admin
from django.contrib.admin.sites import AlreadyRegistered


def _register_all_models(app_label: str) -> None:
	for model in django_apps.get_app_config(app_label).get_models():
		try:
			admin.site.register(model)
		except AlreadyRegistered:
			pass


_register_all_models('agentic')
