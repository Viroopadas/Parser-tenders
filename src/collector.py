import logging

from src.bll.http_worker import HttpWorker
from src.bll.mapper import Mapper
from src.bll.parser import Parser
from src.config import config
from src.repository.mongodb import MongoRepository
from src.repository.rabbitmq import RabbitMqProvider
from time import sleep


class Collector:
    __slots__ = ['logger', '_repository', '_rabbitmq']

    def __init__(self):
        self.logger = logging.getLogger('{}.{}'.format(config.app_id, 'collector'))
        self._repository = None
        self._rabbitmq = None

    @property
    def repository(self):
        if not self._repository:
            self._repository = MongoRepository(config.mongo['host'], config.mongo['port'], config.mongo['database'],
                                               config.mongo['collection'])
        return self._repository

    @property
    def rabbitmq(self):
        if not self._rabbitmq:
            self._rabbitmq = RabbitMqProvider(config.rabbitmq['host'], config.rabbitmq['port'],
                                              config.rabbitmq['username'], config.rabbitmq['password'],
                                              config.rabbitmq['queue'])
        return self._rabbitmq

    def tender_list_gen(self):
        url = 'http://sitno.ru/tender/index.php/tenders_detail.php?LOT_ID=11767&PAGEN_1={}'
        num_page = 1
        while True:
            html = HttpWorker.get_tenders(url.format(str(num_page))).text
            num_page += 1
            tender_list, next_url = Parser.parse_tenders(html)
            if not next_url:
                break
            for x in tender_list:
                self.logger.info('[tender-{}] PARSING STARTED'.format(x['tender_url']))
                res = self.repository.get_one(x['tender_id'])
                if res and res['status'] == 3:
                    self.logger.info('[tender-{}] ALREADY EXIST'.format(x['tender_url']))
                    continue

                mapper = Mapper(id_=x['tender_id'], status=x['tender_status'], http_worker=HttpWorker)
                mapper.load_tender_info(**x)
                yield mapper

                self.logger.info('[tender-{}] PARSING OK'.format(x['tender_url']))

    def collect(self):
        while True:
            for mapper in self.tender_list_gen():
                self.repository.upsert(mapper.tender_short_model)
                for model in mapper.tender_model_gen():
                    self.rabbitmq.publish(model)
            sleep(config.sleep_time)
