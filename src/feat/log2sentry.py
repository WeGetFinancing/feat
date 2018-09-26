try:
    from raven import Client

    _raven_imported = True
except Exception:
    pass
    _raven_imported = False

import os


class SentryReporter(object):
    """
    Capture and report errors to Sentry
    """

    def __init__(self):
        if _raven_imported:
            kwargs = {
                'dsn': os.environ.get('SENTRY_DSN'),
                'include_paths': [
                    'feat',
                    'featcredex',
                    'partner',
                    'getfinancing'
                ],
                'release': os.environ.get('APP_RELEASE', '1.0'),
                'environment': os.environ.get('APP_ENV', 'test')
            }

            try:
                # As we are removing feat, just hack this in for the time being.
                from featcredex.configure import configure as releaseconfig
                kwargs['release'] = releaseconfig.version
                kwargs['tags'] = {}
                kwargs['tags']['revision'] = releaseconfig.version_revision
                kwargs['tags']['revision_date'] = releaseconfig.version_date
                kwargs['tags']['branch'] = releaseconfig.version_branch
                kwargs['tags']['sprint'] = releaseconfig.version_sprint
                import pkg_resources
                kwargs['tags']['feat'] = pkg_resources.get_distribution("feat").version
            except Exception:
                pass

            self.client = Client(**kwargs)

    def get_client(self):
        if _raven_imported:
            return self.client
        return None
