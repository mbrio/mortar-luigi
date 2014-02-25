import abc
import json
from luigi import Task, configuration
import luigi
from luigi.s3 import S3Target
import requests
from requests.auth import HTTPBasicAuth

import logging
from mortar.luigi import target_factory

logger = logging.getLogger('luigi-interface')

class VerifyApi(Task):

    rec_length = luigi.IntParameter(5)

    def output(self):
        return [S3Target(self.output_path(self.__class__.__name__))]

    def headers(self):
        return {'Accept': 'application/json',
                   'Accept-Encoding': 'gzip',
                   'Content-Type': 'application/json',
                   'User-Agent': 'mortar-luigi'}

    def auth(self):
        return HTTPBasicAuth(configuration.get_config().get('recsys', 'email'),
                             configuration.get_config().get('recsys', 'password'))

    def run(self):
        self._verify_api()

        # write an output token to S3 to confirm that we finished
        target_factory.write_file(self.output()[0])

    @abc.abstractmethod
    def _verify_api(self):
        raise RuntimeError("Must implement _verify_api!")

    def _verify_endpoint(self, endpoint_func, ids):
        num_empty = 0
        for item_id in ids:
            endpoint = endpoint_func(item_id)
            response = requests.get(endpoint, auth=self.auth(), headers=self.headers())
            response.raise_for_status()
            if len(response.json()['recommended_items']) < self.rec_length:
                num_empty += 1
                logger.info('Id %s only returned %s results.' % (item_id, len(response.json()['recommended_items'])))
        if num_empty > 2:
            exception_string = 'API verification failed: %s items had insufficient endpoint results' % num_empty
            logger.warn(exception_string)
            if not self.sample_test:
                raise RecsysAPIException(exception_string)

class VerifyItemItemApi(VerifyApi):

    # host for recsys API
    recsys_api_host = luigi.Parameter()

    @abc.abstractmethod
    def item_ids(self):
        return RuntimeError("Must provide list of ids to sanity verify")

    def _item_endpoint(self, item_id):
        return '%s/v1/recommend/items/%s' % (self.recsys_api_host, item_id)

    def _multisources_endpoint(self, item_id):
        return '%s/v1/recommend/multisources?item_id=%s' % (self.recsys_api_host, item_id)

    def _verify_api(self):
        self._verify_endpoint(self._item_endpoint, self.item_ids())
        self._verify_endpoint(self._multisources_endpoint, self.item_ids())

class VerifyUserItemApi(VerifyApi):

    # host for recsys API
    recsys_api_host = luigi.Parameter()

    @abc.abstractmethod
    def user_ids(self):
        return RuntimeError("Must provide list of ids to sanity verify")

    def _user_endpoint(self, user_id):
        return '%s/v1/recommend/users/%s' % (self.recsys_api_host, user_id)

    def _verify_api(self):
        self._verify_endpoint(self._user_endpoint, self.user_ids())

class PromoteDynamoDBTablesToAPI(Task):

    # host for recsys API
    recsys_api_host = luigi.Parameter()

    @abc.abstractmethod
    def table_names(self):
        """
        Dictionary with table names to set.
        """
        raise RuntimeError("Must provide a dictionary of table names to set")

    def output(self):
        return [S3Target(self.output_path(self.__class__.__name__))]

    def run(self):
        self._set_tables()

        # write an output token to S3 to confirm that we finished
        target_factory.write_file(self.output()[0])

    def _client_update_endpoint(self):
        return '%s/v1/clients/%s' % (self.recsys_api_host, self.client_id)

    def _set_tables(self):
        headers = {'Accept': 'application/json',
                   'Accept-Encoding': 'gzip',
                   'Content-Type': 'application/json',
                   'User-Agent': 'mortar-luigi'}
        url = self._client_update_endpoint()
        body = {'ii_table': self.table_names()['ii_table'],
                'ui_table': self.table_names()['ui_table']}
        auth = HTTPBasicAuth(configuration.get_config().get('recsys', 'email'),
                             configuration.get_config().get('recsys', 'password'))
        logger.info('Setting new tables to %s at %s' % (body, url))
        response = requests.put(url, data=json.dumps(body), auth=auth, headers=headers)
        response.raise_for_status()


class RecsysAPIException(Exception):
    pass