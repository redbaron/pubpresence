# -*- coding: utf-8 -*-
from zope.interface import implements
from twisted.internet import defer
from twisted.words.protocols.jabber.xmlstream import IQ
from twisted.words.protocols.jabber.jid import JID
from twisted.words.xish import xpath, domish

from wokkel.iwokkel import IDisco
from wokkel.xmppim import PresenceProtocol
from wokkel.data_form import Form,Field
from wokkel.pubsub import Item

NS_XML = 'http://www.w3.org/XML/1998/namespace'
NS_COMMANDS = 'http://jabber.org/protocol/commands'
NS_ROSTER = 'jabber:iq:roster'
NS_ADMIN = 'http://jabber.org/protocol/admin'
NS_ADMIN_USER_STATS = NS_ADMIN + '#user-stats'

PUB_NODE = "presence" #node name where we publish items

class PublishPresence(PresenceProtocol):  
    implements(IDisco)
    
    def connectionInitialized(self):
        super(PublishPresence,self).connectionInitialized()
        self.pubsub_client.createNode(JID(self.pubsub_name), PUB_NODE, sender=JID(self.name))
          
    def getDiscoInfo(self, requestor, target, nodeIdentifier=''):
        return defer.succeed([])

    def getDiscoItems(self, requestor, target, node):
        return defer.succeed([])
        
    def subscribeReceived(self, presence):     
        user,component = self._getParts(presence)
        self.subscribed(user,sender=component)
        self.available(user,sender=component)
        self.subscribe(user,sender=component)
        
    def unsubscribeReceived(self, presence):
        user,component = self._getParts(presence)
        self.unsubscribed(user,sender=component)

    def probeReceived(self, presence):
        user,component = self._getParts(presence)
        self.available(user,sender=component)
     
    def availableReceived(self, presence, show=None, statuses=None, priority=0):
        """
        We have received presence from user, get it's IP and publish new info
        
        publish format is <user name=jid ip=ip_addr status=status />
        where status could be:
            - online - plain online
            - dnd - do nod distrib
            - away - away
            - xa - really away
            - chat - ready for chat
        
        TODO: handle situations when multiple connections with multiple resources
        """
        user = presence.sender
        comp_name = presence.recipient.userhost()
        domain = user.host
        
        status = presence.show or 'online'
        self.presenceChanged(user,comp_name,domain,status)
        
        
    def unavailableReceived(self, presence):
        user = presence.sender
        comp_name = presence.recipient.userhost()
        domain = user.host
        status = 'offline'
        self.presenceChanged(user,comp_name,domain,status)

    
    def presenceChanged(self,user,comp_name,domain,status):
        """
        Processs change of presence of user
        """
        
        def process_stats(item):
            """
            Process result of user-stats command
            
            Extract IP address and publish it via pubsub
            """
            x = xpath.queryForNodes("//x/field[@var='ipaddresses']",item)
            if not x:
                return
            frm = Form.fromElement(x[0])
            values = frm.getValues()
            jid = JID(values['accountjid'])
            ipport = values['ipaddresses']
            
            ip, port = ipport.split(':')

            #make new item which would be published
            payload = domish.Element((None,"user"))
            payload['name'] = jid.userhost()
            payload['ip'] = ip
            payload['status'] = status
            
            item = Item(payload=payload)
            
            #actually publish item
            self.pubsub_client.publish(JID("pubsub.%s"%domain),PUB_NODE,items=[item],sender=JID(comp_name))
        
        #TODO: implement error handling if ACL doesn't allows us to call admin command
        iq = IQ(self.xmlstream)
        iq['to'] = domain
        iq['from'] = comp_name
        cmd = iq.addElement((NS_COMMANDS,'command'))
        cmd['node'] = NS_ADMIN_USER_STATS
       
        frm = Form('submit')
        frm.addField( Field(fieldType='hidden',var='FORM_TYPE',value=NS_ADMIN) )
        frm.addField( Field(fieldType='jid-single',var='accountjid',value=user.full()) )
        cmd.addChild(frm.toElement())
        d = iq.send(domain)
        d.addCallback(process_stats)
        
        
    def _getParts(self,presence):
        return presence.sender,presence.recipient
