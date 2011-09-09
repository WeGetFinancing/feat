# F3AT - Flumotion Asynchronous Autonomous Agent Toolkit
# Copyright (C) 2010,2011 Flumotion Services, S.A.
# All rights reserved.

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

# See "LICENSE.GPL" in the source distribution for more information.

# Headers in this file shall remain intact.
from feat.agencies import agency, journaler
from feat.common import defer

from feat.agencies.emu import messaging
from feat.agencies.emu import database


class Agency(agency.Agency):

    def initiate(self):
        mesg = messaging.Messaging()
        db = database.Database()
        writer = journaler.SqliteWriter(self)
        journal = journaler.Journaler(self)
        journal.configure_with(writer)
        d = writer.initiate()
        d.addCallback(defer.drop_param, agency.Agency.initiate,
                      self, db, journal, mesg)
        return d
