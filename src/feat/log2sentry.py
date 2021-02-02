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
                'ignore_exceptions': [
                    '_DefGen_Return',
                    'StopIteration'
                ],
                'release': os.environ.get('APP_RELEASE', '1.0'),
                'environment': os.environ.get('APP_ENV', 'test'),
                'tags': {}
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
                kwargs['tags']['profile'] = os.environ.get('PROFILE', 'none')
            except Exception:
                pass

            kwargs['tags'].update(self._get_AWS_tags())

            self.client = Client(**kwargs)

    def _get_AWS_tags(self):
        kwargs = {}
        try:
            path = os.environ.get('ECS_CONTAINER_METADATA_FILE')
            if path is None:
                kwargs['cloud'] = 'local'
            else:
                kwargs['cloud'] = 'aws'
                with file(path) as f:
                    import json
                    meta = json.loads(f.read())
                    for key in (
                            'ContainerName', 'ImageName', 'TaskARN', 'TaskDefinitionFamily', 'TaskDefinitionRevision',
                            'Cluster', 'ImageID'):
                        kwargs[key] = meta.get(key)
        except Exception:
            import traceback
            print traceback.format_exc()
        return kwargs

    def get_client(self):
        if _raven_imported:
            return self.client
        return None
