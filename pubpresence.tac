# -*- coding: utf-8 -*-

"""
Publish users presence information on pubsub node

Usefull if you have to track user activity on corporate desktops
"""

from twisted.application import service
from wokkel import component
from wokkel.disco import DiscoHandler
from wokkel.pubsub import PubSubClient
from pubpresence import PublishPresence

# Configuration parameters

EXT_HOST = 'localhost'
EXT_PORT = 8888
SECRET = 'secret'
DOMAIN = 'example.com'
LOG_TRAFFIC = True
NAME = 'pubpresence.%s'%DOMAIN #the name of component defined in jabber server
PUBSUB_NAME = 'pubsub.%s'%DOMAIN #name of pubsub service


# Set up the Twisted application
application = service.Application("Publish Presence Component")

router = component.Router()
pubpresenceComponent = component.Component(EXT_HOST, EXT_PORT, DOMAIN, SECRET)
pubpresenceComponent.logTraffic = LOG_TRAFFIC 
pubpresenceComponent.setServiceParent(application)

pubsubClient = PubSubClient()
pubsubClient.setHandlerParent(pubpresenceComponent)

pubpresenceHandler = PublishPresence()
pubpresenceHandler.setHandlerParent(pubpresenceComponent)
pubpresenceHandler.name = NAME
pubpresenceHandler.pubsub_name = PUBSUB_NAME
pubpresenceHandler.pubsub_client = pubsubClient

discoHandler = DiscoHandler()
discoHandler.setHandlerParent(pubpresenceComponent)