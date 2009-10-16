# -*- coding: utf-8 -*-

"""
Publish users presence information on pubsub node

Usefull if you have to track user activity on corporate desktops
"""

from twisted.application import service
from wokkel import component
from wokkel.disco import DiscoHandler, DiscoClientProtocol
from wokkel.pubsub import PubSubClient
from pubpresence import PublishPresence

# Configuration parameters
from .config import EXT_HOST,EXT_PORT,SECRET,DOMAIN,LOG_TRAFFIC,\
                    NAME,PUBSUB_NAME



# Set up the Twisted application
application = service.Application("Publish Presence Component")

router = component.Router()
pubpresenceComponent = component.Component(EXT_HOST, EXT_PORT, DOMAIN, SECRET)
pubpresenceComponent.logTraffic = LOG_TRAFFIC 
pubpresenceComponent.setServiceParent(application)

pubsubClient = PubSubClient()
pubsubClient.setHandlerParent(pubpresenceComponent)

discoClient = DiscoClientProtocol()
discoClient.setHandlerParent(pubpresenceComponent)

pubpresenceHandler = PublishPresence()
pubpresenceHandler.setHandlerParent(pubpresenceComponent)
pubpresenceHandler.name = NAME
pubpresenceHandler.pubsub_name = PUBSUB_NAME
pubpresenceHandler.pubsub_client = pubsubClient
pubpresenceHandler.domain = DOMAIN
pubpresenceHandler.disco_client = discoClient

discoHandler = DiscoHandler()
discoHandler.setHandlerParent(pubpresenceComponent)

