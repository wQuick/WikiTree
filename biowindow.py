# WikiTree - WikiTree Integration
#
# Copyright (C) 2021  Hans Boldt
#
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
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

#-------------------#
# Python modules    #
#-------------------#
from html import escape
from datetime import datetime
import json
import requests
import sys

import pdb

#-------------------#
# Gramps modules    #
#-------------------#
from gramps.gen.lib import (Person, EventType, EventRoleType)
from gramps.gen.display.name import displayer as name_displayer
from gramps.gen.datehandler import get_date
from gramps.gen.relationship import get_relationship_calculator
from gramps.gen.utils.db import (get_birth_or_fallback,
                                 get_death_or_fallback)
from gramps.gen.config import config
from gramps.gen.utils.symbols import Symbols
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gen.db import DbTxn

#------------------#
# Gtk modules      #
#------------------#
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib, Gdk

try:
    gi.require_version('WebKit2', '4.0')
    from gi.repository import WebKit2

    import mwparserfromhell
    import mwcomposerfromhell
except:
    pass


# Other gramplet modules
from services import (format_name, format_person_info, format_date,
                      get_wikitree_attributes,
                      get_wikitree_attributes_from_handle,
                      save_wikitree_id_to_person)


#------------------#
# Translation      #
#------------------#
try:
    _trans = glocale.get_addon_translator(__file__)
    _ = _trans.gettext
except ValueError:
    _ = glocale.translation.sgettext
ngettext = glocale.translation.ngettext # else "nearby" comments are ignored


default_template = """==Biography==

%(title)s

%(summary)s

%(names)s

%(events)s

%(notes)s

==Sources==

%(sources)s

Last update: %(lastupdate)s

Biography generated by Gramps gramplet WikiTree v0.1.0 at %(timestamp)s
"""

primary_event_types = (EventType.BIRTH, EventType.DEATH, EventType.MARRIAGE)




#====================================================
#
# Class BioWindow
#
#====================================================

class BioWindow(Gtk.Window):
    """
    """

    def __init__(self, db, person, include_witness_events=False, \
                 include_witnesses=False, include_notes=False):
        """
        """
        self.db = db
        self.person = person
        self.include_witness_events = include_witness_events
        self.include_witnesses = include_witnesses
        self.include_notes = include_notes

        self.relcalc = get_relationship_calculator()

        # Do we have all the necessary Python packages?
        html_ok = False
        try:
            x = mwcomposerfromhell
            html_ok = True
        except NameError:
            pass

        Gtk.Window.__init__(self, title=_("WikiTree Biography"))
        self.set_default_size(800, 800)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.homogenous = False
        box.set_border_width(0)

        # Biography
        bio_notebook = Gtk.Notebook()

        if html_ok:
            html_window = Gtk.ScrolledWindow()
            html_webview = WebKit2.WebView()
            html_window.add(html_webview)
            bio_notebook.append_page(html_window, Gtk.Label(label=_("Formatted")))

        bio_window = Gtk.ScrolledWindow()
        bio_label = Gtk.Label(label='')
        bio_label.set_yalign(0)
        bio_label.set_xalign(0)
        bio_window.add(bio_label)
        bio_notebook.append_page(bio_window, Gtk.Label(label=_("WikiCode")))

        box.pack_start(bio_notebook, expand=True, fill=True, padding=0)

        # Buttons
        copy_button = Gtk.Button.new_with_label(_("Copy to Clipboard"))
        copy_button.connect('clicked', self.on_click_copy)
        box.pack_start(copy_button, expand=False, fill=False, padding=0)

        self.add(box)
        box.show_all()
        self.show_all()

        # Create biography
        self.sources = {}
        values = {}

        # Locate template
        template = default_template
        header = ''
        footer = ''
        for note_handle in self.db.iter_note_handles():
            note = self.db.get_note_from_handle(note_handle)
            note_type = note.get_type().string
            if note_type == 'WikiTree Template':
                template = str(note.text)
            elif note_type == 'WikiTree Header':
                header = str(note.text)
            elif note_type == 'WikiTree Footer':
                footer = str(note.text)

        # Do we want a "header" section?
        if '%(title)s' in template:
            values['title'] = self.format_title()

        # Do we want a "header" section?
        if '%(summary)s' in template:
            values['summary'] = self.format_summary()

        # Do we want a "names" section?
        if '%(names)s' in template:
            values['names'] = self.format_names()

        # Do we want an "Events" section?
        if '%(events)s' in template:
            values['events'] = self.format_events()

        # Do we want a "Notes" section?
        if self.include_notes and '%(notes)s' in template:
            values['notes'] = self.format_notes()

        # Required content: sources, lastupdate, timestamp
        values['sources'] = self.format_sources()
        values['lastupdate'] = self.format_lastupdate()
        values['timestamp'] = str(datetime.now()).split('.')[0]

        # Fill values
        self.biography = "%s\n%s\n%s" \
                % ((header+"\n" if header else ''),
                    (template % values),
                    (footer+"\n" if footer else ''))

        bio_label.set_text(self.biography)
        if html_ok:
            wikicode = mwparserfromhell.parse(self.biography)
            html = mwcomposerfromhell.compose(wikicode)
            html_webview.load_html(html, None)


    def on_click_copy(self, button):
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text(self.biography, -1)
        return True


    def format_title(self):
        name = self.person.get_primary_name()
        full_name = name.get_first_name() + ' ' + name.get_surname()
        citations = self.person.get_citation_list()
        cit_str = self.add_citations(citations) if citations else ''
        res = "<b>%s</b> %s\n" % (full_name, cit_str)
        return res


    def get_spouses(self, person_handle):
        """
        Return list of spouses for given person.
        """
        spouses = list()
        db = self.dbstate.db
        person = db.get_person_from_handle(person_handle)
        gender = person.get_gender()

        # Loop through all families
        for family_handle in person.get_family_handle_list():
            family = db.get_family_from_handle(family_handle)
            if not family:
                continue

            if gender == Person.MALE:
                spouse_handle = family.get_mother_handle()
            else:
                spouse_handle = family.get_father_handle()

            if spouse_handle:
                spouses.append(spouse_handle)

        return spouses


    def format_summary(self):
        res = "===Summary===\n\n<p>"

        # Information about person
        gender = self.person.get_gender()
        wt_attrs = get_wikitree_attributes(self.db, self.person)
        if wt_attrs:
            res += '<b>WikiTree Id:</b> ' + wt_attrs['id'] + "<br/>\n"

        # Birth and death dates:
        birth_event = get_birth_or_fallback(self.db, self.person)
        if birth_event:
            place_handle = birth_event.get_place_handle()
            place = (', ' + self.get_full_place_name(place_handle)) if place_handle else ''
            res += "<b>" + birth_event.get_type().string + ":</b> " \
                + get_date(birth_event) + place + "<br/>\n"

        death_event = get_death_or_fallback(self.db, self.person)
        if death_event:
            place_handle = death_event.get_place_handle()
            place = (', ' + self.get_full_place_name(place_handle)) if place_handle else ''
            res += "<b>" + death_event.get_type().string + ":</b> " \
                + get_date(death_event) + place + "<br/>\n"

        # Extract parents
        mother, father = self.relcalc.get_birth_parents(self.db, self.person)
        if father:
            res += '<b>Father:</b> ' + self.format_clickable_name(father) + "<br/>\n"
        if mother:
            res += '<b>Mother:</b> ' + self.format_clickable_name(mother) + "<br/>\n"

        # Extract spouses and children
        for family_handle in self.person.get_family_handle_list():
            family = self.db.get_family_from_handle(family_handle)
            if not family:
                continue

            # Get name of spouse
            if gender == Person.MALE:
                res += '<b>Wife:</b> ' \
                    + self.format_clickable_name(family.get_mother_handle()) \
                    + "<br/>\n"
            else:
                res += '<b>Husband:</b> ' \
                    + self.format_clickable_name(family.get_father_handle()) \
                    + "<br/>\n"

            # Get children for spouse:
            child_ref_list = family.get_child_ref_list()
            if child_ref_list:
                res += "<b>Children:</b>\n<ol>\n"
                for child_ref in child_ref_list:
                    res += "<li>" + self.format_clickable_name(child_ref.ref) + "</li>\n"
                res += "</ol><br/>\n"

        return res + "</p>\n"


    def format_names(self):
        res = "===Names===\n\n<ul>\n"

        primary_name = self.person.get_primary_name()
        res += self.format_one_name(primary_name)

        for name in self.person.get_alternate_names():
            res += self.format_one_name(name)

        res += '</ul>'
        return res


    def format_one_name(self, name):

        first_name = name.get_first_name()
        last_name = name.get_surname()
        name_type = name.get_type()
        full_name = first_name + ' ' + last_name

        surname_list = name.get_surname_list()
        surname_type = surname_list[0].origintype.string
        if surname_type:
            surname_type = ' (' + surname_type + ')'

        citations = name.get_citation_list()
        cit_str = self.add_citations(citations) if citations else ''

        res_name = "<li><b>" + str(name_type) + ":</b> " + full_name + surname_type + cit_str + "</li>\n"

        return res_name


    def format_events(self):
        res = "===Events===\n\n"
        events = self.get_events(children=True)
        self.parents_listed = False

        # Locate last event, either Death or Burial
        last_event = None
        for ev in events:
            if ev['events'][0]['role'] == 'Primary':
                event_type = ev['events'][0]['event'].get_type()
                if event_type in [EventType.DEATH, EventType.BURIAL]:
                    last_event = ev

        # Output list of events
        res += "<ul>\n"
        for one_date in events:
            evres = "<li><b>" + one_date['datestr'] + "</b><br/>\n"
            evres += "<ul>\n"
            event_count = 0
            for ev in one_date['events']:
                if not self.include_witness_events    \
                and ev['role'] in ['Witness', 'Informant']:
                    continue
                evres += '<li>' + self.format_one_event(ev['event'], ev['role']) + "</li>\n"
                event_count += 1
            evres += "</ul>\n"
            evres += "</li>\n"
            if event_count > 0:
                res += evres

            if one_date == last_event:
                break
        res += "</ul>\n"
        return res


    def format_one_event(self, event, role):
        res = ''
        primary_roles = ['Primary', 'Family']
        event_type = event.get_type()

        # Print role if not primary
        rolestr = ''
        if role not in primary_roles:
            rolestr = role + ' at '

        # Get citations
        citations = event.get_citation_list()
        cit_str = self.add_citations(citations) if citations else ''

        # Add other participants
        participants_str = ''
        participants = self.get_event_participants(event)
        descr_str = event.get_description()
        descr_str = (descr_str + ' ') if descr_str else ''
        witness_str = None

        if role == 'Primary':
            if event_type in [EventType.BIRTH, EventType.BAPTISM]:
                if not self.parents_listed:
                    self.parents_listed = True
                    father, mother = self.relcalc.get_birth_parents(self.db, self.person)
                    fname = self.format_clickable_name(father, include_dates=False) if father else ''
                    mname = self.format_clickable_name(mother, include_dates=False) if mother else ''
                    participants_str = 'to parents: ' + fname + ', ' + mname + ' '

                if self.include_witnesses:
                    witnesses = self.filter_participants(participants, EventRoleType.WITNESS)
                    if len(witnesses) > 1:
                        witstr = _('Witness') if len(witnesses) == 1 else _('Witnesses')
                        comma = ''
                        witness_str = "<b>%s:</b> " % witstr
                        for wit in witnesses:
                            witness_str += comma + self.format_clickable_name(wit[1], include_dates=False)
                            comma = ', '

        elif role == 'Family':
            if event_type == EventType.MARRIAGE:
                family = None
                for p in participants:
                    if p[0] == 'Family':
                        family = self.db.get_family_from_handle(p[1])
                if family:
                    father_handle = family.get_father_handle()
                    if father_handle == self.person.get_handle():
                        spouse_handle = family.get_mother_handle()
                    else:
                        spouse_handle = father_handle
                    participants_str = 'to ' + self.format_clickable_name(spouse_handle, include_dates=False) + ' '

                if self.include_witnesses:
                    witnesses = self.filter_participants(participants, EventRoleType.WITNESS)
                    if len(witnesses) > 1:
                        witstr = _('Witness') if len(witnesses) == 1 else _('Witnesses')
                        comma = ''
                        witness_str = "<b>%s:</b> " % witstr # -760,-28
                        for wit in witnesses:
                            witness_str += comma + self.format_clickable_name(wit[1], include_dates=False)
                            comma = ', '

        elif role == 'Parent':
            rolestr = ''
            child_handle = self.filter_participants(participants, EventRoleType.PRIMARY)[0][1]
            child = self.db.get_person_from_handle(child_handle)
            child_gender = child.get_gender()
            if child_gender == Person.MALE:
                child_str = 'son '
            elif child_gender == Person.FEMALE:
                child_str = 'daughter '
            else:
                child_str = ''
            participants_str =  'of ' + child_str + self.format_clickable_name(child_handle, include_dates=False)

        elif role == 'Spouse':
            rolestr = ''
            spouse_handle = self.filter_participants(participants, EventRoleType.PRIMARY)[0][1]
            spouse = self.db.get_person_from_handle(spouse_handle)
            spouse_gender = spouse.get_gender()
            if spouse_gender == Person.MALE:
                spouse_str = 'husband '
            else:
                spouse_str = 'wife '
            participants_str =  'of ' + spouse_str + self.format_clickable_name(spouse_handle, include_dates=False)

        elif role in ['Witness', 'Informant']:
            family = None
            for p in participants:
                if p[0] == 'Family':
                    family = self.db.get_family_from_handle(p[1])

            if family:
                husb_handle = family.get_father_handle()
                wife_handle = family.get_mother_handle()
                hname = self.format_clickable_name(husb_handle, include_dates=False) if husb_handle else ''
                wname = self.format_clickable_name(wife_handle, include_dates=False) if wife_handle else ''
                participants_str = 'of ' + hname + ' and ' + wname + ' '
            else:
                primary_handle = self.filter_participants(participants, EventRoleType.PRIMARY)[0][1]
                participants_str = 'of ' + self.format_clickable_name(primary_handle, include_dates=False) + ' '

        # Construct event string
        res += rolestr + "<b>" + event.get_type().string + "</b> " \
            + descr_str \
            + participants_str + ' ' + cit_str + "\n"

        # Add list of witnesses
        if witness_str:
            res += "<br/>" + witness_str + "\n"

        # Add place name
        place_handle = event.get_place_handle()
        if place_handle:
            res += "<br/>" + self.get_full_place_name(place_handle) + "\n"
        return res


    def get_full_place_name(self, place_handle):
        comma = ''
        res = ''
        while place_handle:
            place = self.db.get_place_from_handle(place_handle)
            res += comma + place.name.get_value()
            comma = ', '

            placeref_list = place.get_placeref_list()
            if placeref_list:
                place_handle = placeref_list[0].ref
            else:
                place_handle = None
        return res


    def get_event_participants(self, event):
        res_participants = list()
        event_handle = event.get_handle()
        participants = list(self.db.find_backlink_handles(event_handle,
                                    include_classes=['Person', 'Family']))

        # Determine roles for each participant
        for p in participants:
            plist = list(p)
            if p[0] == 'Person':
                person = self.db.get_person_from_handle(p[1])
                event_refs = person.get_event_ref_list()
                for evref in event_refs:
                    if evref.ref == event_handle:
                        plist.append(evref.get_role())
                        break
            elif p[0] == 'Family':
                family = self.db.get_family_from_handle(p[1])
                event_refs = family.get_event_ref_list()
                for evref in event_refs:
                    if evref.ref == event_handle:
                        plist.append(evref.get_role())
                        break
            res_participants.append(plist)

        return res_participants


    def filter_participants(self, participants, role):
        return [x for x in participants if x[2] == role]


    def format_clickable_name(self, person_handle, include_dates=True):
        if not person_handle:
            return ''

        person = self.db.get_person_from_handle(person_handle)
        private = person.get_privacy()
        if private:
            return '(private)'

        name = person.get_primary_name()
        name_str = name.get_first_name() + ' ' + name.get_surname()
        wt_attrs = get_wikitree_attributes(self.db, person)
        if wt_attrs:
            res = '[[%s|%s]]' % (wt_attrs['id'], name_str)
        else:
            res = name_str

        if include_dates:
            res += ' ' + self._info_string(person)
        return res


    def get_events(self, children=False):
        events = list()

        gender = self.person.get_gender()

        # Get events for person
        event_ref_list = self.person.get_event_ref_list()
        for event_ref in event_ref_list:
            event = self.db.get_event_from_handle(event_ref.ref)
            ev = {'date': event.get_date_object(),
                  'datestr': (get_date(event) or '- - - - -'),
                  'events': [ {
                        'role': event_ref.role.string,
                        'event': event,
                        'eventref': event_ref} ] }
            events.append(ev)

        # Get family marriage and child birth/death events
        for family_handle in self.person.get_family_handle_list():
            family = self.db.get_family_from_handle(family_handle)

            # Get family events
            for event_ref in family.get_event_ref_list():
                event = self.db.get_event_from_handle(event_ref.ref)
                ev = {'date': event.get_date_object(),
                      'datestr': get_date(event),
                      'events': [ {
                            'role': event_ref.role.string,
                            'event': event ,
                            'eventref': event_ref} ] }
                self.merge_event(events, ev)

                # Get death event for spouse
                if gender == Person.MALE:
                    spouse_handle = family.get_mother_handle()
                else:
                    spouse_handle = family.get_father_handle()
                if spouse_handle:
                    spouse = self.db.get_person_from_handle(spouse_handle)
                    death_event = get_death_or_fallback(self.db, spouse)
                    if death_event:
                        ev = {'date': death_event.get_date_object(),
                              'datestr': get_date(death_event),
                              'events': [ {
                                    'role': 'Spouse',
                                    'event': death_event,
                                    'eventref': None } ] }
                        self.merge_event(events, ev)

            # Get birth and death events for children
            if children:
                for child_ref in family.get_child_ref_list():
                    child = self.db.get_person_from_handle(child_ref.ref)

                    birth_event = get_birth_or_fallback(self.db, child)
                    if birth_event:
                        ev = {'date': birth_event.get_date_object(),
                              'datestr': get_date(birth_event),
                              'events': [ {
                                    'role': 'Parent',
                                    'event': birth_event,
                                    'eventref': None } ] }
                        self.merge_event(events, ev)

                    death_event = get_death_or_fallback(self.db, child)
                    if death_event:
                        ev = {'date': death_event.get_date_object(),
                              'datestr': get_date(death_event),
                              'events': [ {
                                    'role': 'Parent',
                                    'event': death_event,
                                    'eventref': None } ] }
                        self.merge_event(events, ev)

        # Merge events with same date
        res_events = list()
        while events:
            ev = events.pop(0)
            if res_events and res_events[-1]['date'] == ev['date']:
                event_type = ev['events'][0]['event'].get_type()
                if event_type in primary_event_types \
                and ev['events'][0]['role'] == 'Primary':
                    res_events[-1]['events'].insert(0, ev['events'][0])
                else:
                    res_events[-1]['events'].append(ev['events'][0])
            else:
                res_events.append(ev)

        # pdb.set_trace()
        res_events.sort(key=lambda x: x['date'])
        return res_events


    def merge_event(self, event_list, event):
        i = 0
        while i < len(event_list):
            event_date = event_list[i]['date']
            if event_date and event_date > event['date']:
                event_list.insert(i, event)
                return
            i += 1
        event_list.append(event)


    def format_notes(self):
        res = "===Notes===\n"
        note_list = self.person.get_note_list()
        if note_list:
            res += "<ul>\n"
            for note_handle in note_list:
                note = self.db.get_note_from_handle(note_handle)
                res += "<li>%s<br/>\n" % note.get_type().string
                if note.get_privacy():
                    res += "(private)\n"
                else:
                    res += self.format_note_text(note.get_styledtext())
                res += "</li>\n"
            res += "</ul>\n"
        return res


    def format_sources(self):
        res = ''

        res += '<ol style="list-style-type:decimal">' + "\n"
        for src_key in self.sources:
            src = self.sources[src_key]
            res += "<li>%s\n" % src['src'].get_title()

            res += '<ol style="list-style-type:lower-alpha">' + "\n"

            for cit_handle in src['citation handles']:
                citation = self.db.get_citation_from_handle(cit_handle)
                page = citation.get_page()
                date = get_date(citation)
                media_list = citation.get_media_list()
                note_list = citation.get_note_list() if self.include_notes else None

                res += "<li>"
                if date:
                    res += "<b>Date:</b> %s<br/>\n" % date
                if page:
                    res += "<b>Page:</b> %s<br/>\n" % page
                if media_list:
                    res += "<b>Media:</b><ul>\n"
                    for mediaref in media_list:
                        media = self.db.get_media_from_handle(mediaref.ref)
                        res += "<li><b>Description:</b> %s<br/>\n" % media.get_description()
                        res += "<b>Path:</b> %s</li>\n" % media.get_path()
                    res += "</ul>\n"
                if note_list:
                    res += "<b>Notes:</b><ul>\n"
                    for note_handle in note_list:
                        note = self.db.get_note_from_handle(note_handle)
                        res += "<li>%s<br/>\n" % note.get_type().string
                        if note.get_privacy():
                            res += "(private)\n"
                        else:
                            res += self.format_note_text(note.get_styledtext())
                        res += "</li>\n"
                    res += "</ul>\n"

                res += "</li>\n"
            res += "</ol></li><br/>\n"
        res += "</ol>\n"

        return res


    def format_note_text(self, text):
        res = '<p>'
        lines = [a.string for a in text.split("\n")]
        res += "<br/>\n".join(lines)
        return res + "</p>\n"



    def format_lastupdate(self):
        date = self.person.get_change_time()
        return datetime.fromtimestamp(date).strftime(
                    '%Y-%m-%d %H:%M:%S')


    def add_citations(self, citations):
        res_cit_str = ''

        for cit_handle in citations:
            citation = self.db.get_citation_from_handle(cit_handle)
            source_handle = citation.source_handle
            source = self.db.get_source_from_handle(source_handle)

            if source_handle in self.sources:
                src_num = self.sources[source_handle]['num']
                if cit_handle in self.sources[source_handle]['citation handles']:
                    i = self.sources[source_handle]['citation handles'].index(cit_handle)
                    cit_num = self._get_cit_number(i)
                else:
                    self.sources[source_handle]['citation handles'].append(cit_handle)
                    cit_num = self._get_cit_number(len(self.sources[source_handle]['citation handles'])-1)
            else:
                self.sources[source_handle] = {
                        'num': str(len(self.sources)+1),
                        'src': source,
                        'citation handles': [cit_handle]
                    }
                src_num = self.sources[source_handle]['num']
                cit_num = 'a'

            cit_str = src_num + cit_num
            res_cit_str += '<sup>[%s]</sup>' % cit_str

        if res_cit_str:
            res_cit_str = ' ' + res_cit_str
        return res_cit_str


    def _get_cit_number(self, n):
        alpha = 'abcdefghijklmnopqrstuvwxyz'
        b = 26
        if n == 0:
            return 'a'
        digits = []
        first = True
        while n:
            dig = n%b
            if not first:
                dig -= 1
            digits.append(dig)
            n //= b
            first = False
        digits.reverse()
        return ''.join([alpha[x] for x in digits])


    def _fmt_date(self, event, preferred_event_type):
        """
        Format the given date.
        """
        if not event:
            return ''
        sdate = get_date(event)
        if not sdate:
            return ''
        sdate = escape(sdate)
        date_type = event.get_type()
        if preferred_event_type == EventType.BIRTH:
            if date_type != preferred_event_type:
                return "~<i>%s</i>" % sdate
            return "*%s" % sdate
        else:
            if date_type != preferred_event_type:
                return "[]<i>%s</i>" % sdate
            return "+%s" % sdate

        return sdate


    def _info_string(self, person):
        """
        Information string for a person, including date of birth (or baptism)
        and date of death (or burial).
        """
        bdate = self._fmt_date(get_birth_or_fallback(self.db, person), EventType.BIRTH)
        ddate = self._fmt_date(get_death_or_fallback(self.db, person), EventType.DEATH)

        if bdate and ddate:
            return "(%s, %s)" % (bdate, ddate)
        if bdate:
            return "(%s)" % (bdate)
        if ddate:
            return "(%s)" % (ddate)
        return ''
