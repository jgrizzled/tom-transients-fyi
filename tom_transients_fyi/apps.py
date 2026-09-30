from django.apps import AppConfig


class TomTransientsFyiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'tom_transients_fyi'

    def data_services(self):
        """The TOM Toolkit's integration point for data services (tom_dataservices)."""
        return [{'class': f'{self.name}.transients_fyi.TransientsFyiDataService'}]
