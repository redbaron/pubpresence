# -*- coding: utf-8 -*-

from wokkel.pubsub import PubSubRequest

class PubSubRequestWithConf(PubSubRequest):

    def _parse_configure(self, verbElement):
        """
        Parse options out of a request for setting the node configuration.
        """
        form = PubSubRequest._findForm(verbElement, NS_PUBSUB_NODE_CONFIG)
        if form:
            if form.formType == 'submit' or form.formType == 'cancel':
                self.configureForm = form
            else:
                raise BadRequest(text="Unexpected form type %r" % form.formType)
        else:
            raise BadRequest(text="Missing configuration form")

    def _render_configure(self,verbElement):
        verbElement.addChild(self.configureForm.toElement())
