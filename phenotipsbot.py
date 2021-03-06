# PhenoTipsBot
# Framework for manipulating patient data on a PhenoTips server
#
# Copyright 2015 University of Utah
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301
# USA

import json
import requests
from base64 import b64encode
from collections import OrderedDict
from copy import copy
from os.path import basename
from selenium import webdriver
from xml.etree import ElementTree

class PhenoTipsBot:
    TIMEOUT = 20 #seconds

    driver = None

    def __init__(self, base_url, username, password, ssl_verify=True):
        self.base = base_url
        self.auth = (username, password)
        self.ssl_verify = ssl_verify

    def create(self, patient_obj=None, study=None, owner=None, pedigree=None):
        r = requests.post(self.base + '/rest/patients', auth=self.auth, verify=self.ssl_verify)
        r.raise_for_status()
        patient_id = r.headers['location']
        patient_id = patient_id[patient_id.rfind('/')+1:]
        if patient_obj:
            self.set(patient_id, patient_obj)
        if study:
            self.set_study(patient_id, study)
        if owner:
            self.set_owner(patient_id, owner)
        if pedigree:
            self.set_pedigree(patient_id, pedigree)
        #the mandatory PhenoTips.VCF object is not added until someone visits the edit page
        url = self.base + '/bin/edit/data/' + patient_id
        r = requests.get(url, auth=self.auth, verify=self.ssl_verify);
        r.raise_for_status()
        return patient_id

    def create_collaborator(self, patient_id, collaborator_obj):
        if 'collaborator' in collaborator_obj:
            collaborator_obj = copy(collaborator_obj)
            collaborator_obj['collaborator'] = PhenoTipsBot.qualify(collaborator_obj['collaborator'])
        return self.create_object(self, patient_id, 'PhenoTips.CollaboratorClass', collaborator_obj)

    def create_object(self, patient_id, object_class, object_obj):
        url = self.base + '/rest/wikis/xwiki/spaces/data/pages/' + patient_id + '/objects'
        data = {'className': object_class}
        for key, value in object_obj.items():
            data['property#' + key] = value
        r = requests.post(url, auth=self.auth, data=data, verify=self.ssl_verify)
        r.raise_for_status()
        object_number = r.headers['location']
        object_number = object_number[object_number.rfind('/')+1:]
        return object_number

    def create_relative(self, patient_id, relative_obj):
        return self.create_object(patient_id, 'PhenoTips.RelativeClass', relative_obj)

    def create_vcf(self, patient_id, vcf_obj):
        return self.create_object(patient_id, 'PhenoTips.VCF', vcf_obj)

    def delete(self, patient_id):
        r = requests.delete(self.base + '/rest/patients/' + patient_id, auth=self.auth, verify=self.ssl_verify)
        r.raise_for_status()

    def delete_collaborator(self, patient_id, collaborator_num):
        self.delete_object(patient_id, 'PhenoTips.CollaboratorClass', collaborator_num)

    def delete_file(self, patient_id, filename):
        url = self.base + '/rest/wikis/xwiki/spaces/data/pages/' + patient_id + '/attachments/' + filename
        r = requests.delete(url, auth=self.auth, verify=self.ssl_verify)
        r.raise_for_status()

    def delete_object(self, patient_id, object_class, object_num):
        url = self.base + '/rest/wikis/xwiki/spaces/data/pages/' + patient_id + '/objects/' + object_class + '/' + relative_num
        r = requests.delete(url, auth=self.auth, verify=self.ssl_verify)
        r.raise_for_status()

    def delete_relative(self, patient_id, relative_num):
        self.delete_object(patient_id, 'PhenoTips.RelativeClass', relative_num)

    def delete_vcf(self, patient_id, vcf_num):
        self.delete_object(patient_id, 'PhenoTips.VCF', vcf_num)

    def download_file(self, patient_id, filename, outpath):
        fd = open(outpath, "wb")
        fd.write(self.get_file(patient_id, filename))
        fd.close()

    def export_pedigree_ped(self, patient_id, id_generation='external'):
        self.init_phantom()
        url = self.base + '/bin/' + patient_id + '?sheet=PhenoTips.PedigreeEditor'
        self.driver.get(url)
        self.driver.find_element_by_css_selector('#canvas svg') #wait for the page to load
        return self.driver.execute_script('return window.PedigreeExport.exportAsPED(window.editor.getGraph().DG, ' + json.dumps(id_generation) + ');')

    def get(self, patient_id):
        return self.get_object(patient_id, 'PhenoTips.PatientClass', '0')

    def get_collaborator(self, patient_id, collaborator_num):
        ret = self.get_object(patient_id, 'PhenoTips.CollaboratorClass', collaborator_num)
        ret['collaborator'] = PhenoTipsBot.unqualify(ret['collaborator'])
        return ret

    def get_file(self, patient_id, filename):
        url = self.base + '/bin/download/data/' + patient_id + '/' + filename
        r = requests.get(url, auth=self.auth, verify=self.ssl_verify)
        r.raise_for_status()
        return r.content

    def get_id(self, external_id):
        url = self.base + '/rest/patients/eid/' + external_id
        r = requests.get(url, auth=self.auth, verify=self.ssl_verify)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        content_type = r.headers['content-type'].split(';')[0]
        if content_type == 'application/json':
            return json.loads(r.text)['id']
        elif content_type == 'application/xml':
            root = ElementTree.fromstring(r.text)
            id_elements = root.findall('./{http://www.xwiki.org}alternatives/{http://www.xwiki.org}patient/{http://www.xwiki.org}id')
            return list(map(lambda el: el.text, id_elements))
        else:
            raise TypeError('Expected JSON or XML')

    def get_object(self, patient_id, object_class, object_num):
        url = self.base + '/rest/wikis/xwiki/spaces/data/pages/' + patient_id + '/objects/' + object_class + '/' + object_num
        r = requests.get(url, auth=self.auth, verify=self.ssl_verify)
        r.raise_for_status()
        root = ElementTree.fromstring(r.text)
        ret = {}
        for prop in root.iter('{http://www.xwiki.org}property'):
            ret[prop.attrib['name']] = prop.find('{http://www.xwiki.org}value').text
        return ret

    def get_owner(self, patient_id):
        return PhenoTipsBot.unqualify(self.get_object(patient_id, 'PhenoTips.OwnerClass', '0')['owner'])

    def get_pedigree(self, patient_id):
        return json.loads(self.get_object(patient_id, 'PhenoTips.PedigreeClass', '0')['data'])

    def get_relative(self, patient_id, relative_num):
        return self.get_object(patient_id, 'PhenoTips.RelativeClass', relative_num)

    def get_study(self, patient_id):
        url = self.base + '/rest/wikis/xwiki/spaces/data/pages/' + patient_id + '/objects/PhenoTips.StudyBindingClass/0'
        r = requests.get(url, auth=self.auth, verify=self.ssl_verify)
        if r.status_code == 404:
            return None
        else:
            r.raise_for_status()
            root = ElementTree.fromstring(r.text)
            el = root.find('{http://www.xwiki.org}property[@name="studyReference"]/{http://www.xwiki.org}value')
            if not el.text:
                return ''
            else:
                return PhenoTipsBot.unqualify(el.text, 'Studies')

    def get_vcf(self, patient_id, vcf_num):
        return self.get_object(patient_id, 'PhenoTips.VCF', vcf_num)

    def import_pedigree_ped(self, patient_id, pedigree_str, mark_evaluated=False, external_id_mark=True, accept_unknown_phenotypes=True):
        self.init_phantom()
        url = self.base + '/bin/' + patient_id + '?sheet=PhenoTips.PedigreeEditor'
        data = json.dumps(pedigree_str)
        import_options = json.dumps({
            'markEvaluated': mark_evaluated,
            'externalIdMark': external_id_mark,
            'acceptUnknownPhenotypes': accept_unknown_phenotypes
        })
        self.driver.get(url)
        self.driver.find_element_by_css_selector('#canvas svg') #wait for the page to load
        self.driver.execute_script('window.editor.getSaveLoadEngine().createGraphFromImportData(' + data + ', "ped", ' + import_options + ');')
        self.driver.execute_script('window.editor.getSaveLoadEngine().save();')
        self.driver.find_element_by_css_selector('#action-save.menu-item') #wait for the image to be saved

    def init_phantom(self):
        if not self.driver:
            authorization = 'Basic ' + b64encode((self.auth[0] + ':' + self.auth[1]).encode('utf-8')).decode('utf-8')
            webdriver.DesiredCapabilities.PHANTOMJS['phantomjs.page.customHeaders.authorization'] = authorization
            self.driver = webdriver.PhantomJS()
            self.driver.set_window_size(1920, 1080) #big enough to not cut off any elements
            self.driver.implicitly_wait(PhenoTipsBot.TIMEOUT)

    def list(self, study=None, owner=None, having_object=None):
        query = ", BaseObject as obj"
        if study != None:
            query += ", BaseObject as study_obj, StringProperty as study_prop"
        if owner:
            query += ", BaseObject as owner_obj, StringProperty as owner_prop"
        if having_object:
            query += ", BaseObject as needful_obj"
        query += " where doc.space = 'data' and doc.fullName = obj.name and obj.className = 'PhenoTips.PatientClass'"
        if having_object:
            query += " and doc.fullName = needful_obj.name and needful_obj.className = '" + having_object + "'"
        if study != None:
            query += " and doc.fullName = study_obj.name and study_obj.className = 'PhenoTips.StudyBindingClass'"
            query += " and study_obj.id = study_prop.id.id and study_prop.id.name = 'studyReference'"
            query += " and study_prop.value = 'xwiki:Studies." + study + "'"
        if owner:
            query += " and doc.fullName = owner_obj.name and owner_obj.className = 'PhenoTips.OwnerClass'"
            query += " and owner_obj.id = owner_prop.id.id and owner_prop.id.name = 'owner'"
            query += " and owner_prop.value = '" + PhenoTipsBot.qualify(owner) + "'"
        return list(map(lambda pagename: PhenoTipsBot.unqualify(pagename, 'data'), self.list_hql(query)))

    def list_class_properties(self, class_name):
        url = self.base + '/rest/wikis/xwiki/classes/' + class_name
        r = requests.get(url, auth=self.auth, verify=self.ssl_verify)
        r.raise_for_status()
        root = ElementTree.fromstring(r.text)
        ret = OrderedDict()
        for prop in root.iter('{http://www.xwiki.org}property'):
            prop_name = prop.attrib['name']
            ret[prop_name] = {'type': prop.attrib['type']}

            number_type_el = prop.find('./{http://www.xwiki.org}attribute[@name="numberType"]')
            regex_el = prop.find('./{http://www.xwiki.org}attribute[@name="validationRegExp"]')
            values_el = prop.find('./{http://www.xwiki.org}attribute[@name="values"]')

            if number_type_el != None:
                ret[prop_name]['numberType'] = number_type_el.attrib['value']
            if regex_el != None:
                ret[prop_name]['validationRegExp'] = regex_el.attrib['value']
            if values_el != None:
                ret[prop_name]['values'] = {}
                for key_value_pair in values_el.attrib['value'].split('|'):
                    key_value_pair = key_value_pair.split('=')
                    if len(key_value_pair) > 1:
                        key = key_value_pair[0]
                        value = key_value_pair[1]
                    else:
                        key = value = key_value_pair[0]
                    ret[prop_name]['values'][key] = value
        return ret

    def list_collaborators(self, patient_id):
        return self.list_objects(patient_id, 'PhenoTips.CollaboratorClass')

    def list_groups(self):
        return self.list_pages('Groups', 'PhenoTips.PhenoTipsGroupClass')

    def list_hql(self, query):
        url = self.base + '/rest/wikis/xwiki/query'
        r = requests.get(url, params={'q': query, 'type': 'hql'}, auth=self.auth, verify=self.ssl_verify)
        r.raise_for_status()
        root = ElementTree.fromstring(r.text)
        id_elements = root.findall('./{http://www.xwiki.org}searchResult/{http://www.xwiki.org}id')
        return list(map(lambda el: el.text, id_elements))

    def list_objects(self, patient_id, object_class):
        url = self.base + '/rest/wikis/xwiki/spaces/data/pages/' + patient_id + '/objects/' + object_class
        r = requests.get(url, auth=self.auth, verify=self.ssl_verify)
        r.raise_for_status()
        root = ElementTree.fromstring(r.text)
        number_elements = root.findall('./{http://www.xwiki.org}objectSummary/{http://www.xwiki.org}number')
        return list(map(lambda el: el.text, number_elements))

    def list_pages(self, space, having_object=None):
        query = ", BaseObject as obj where doc.space = '" + space + "'"
        if having_object:
            query += " and doc.fullName = obj.name and obj.className = '" + having_object + "'"
        return list(map(lambda pagename: PhenoTipsBot.unqualify(pagename, space), self.list_hql(query)))

    def list_patient_class_properties(self):
        return self.list_class_properties('PhenoTips.PatientClass')

    def list_relatives(self, patient_id):
        return self.list_objects(patient_id, 'PhenoTips.RelativeClass')

    def list_studies(self):
        return self.list_pages('Studies', 'PhenoTips.StudyClass')

    def list_users(self):
        return self.list_pages('XWiki', 'XWiki.XWikiUsers')

    def list_vcfs(self, patient_id):
        return self.list_objects(patient_id, 'PhenoTips.VCF')

    def set(self, patient_id, patient_obj):
        self.set_object(patient_id, 'PhenoTips.PatientClass', '0', patient_obj)

    def set_collaborator(self, patient_id, collaborator_num, collaborator_obj):
        if 'collaborator' in collaborator_obj:
            collaborator_obj = copy(collaborator_obj)
            collaborator_obj['collaborator'] = PhenoTipsBot.qualify(collaborator_obj['collaborator'])
        self.set_object(patient_id, 'PhenoTips.CollaboratorClass', collaborator_num, collaborator_obj)

    def set_file(self, patient_id, filename, contents):
        url = self.base + '/rest/wikis/xwiki/spaces/data/pages/' + patient_id + '/attachments/' + filename
        r = requests.put(url, auth=self.auth, data=contents, verify=self.ssl_verify)
        r.raise_for_status()

    def set_object(self, patient_id, object_class, object_num, object_obj):
        url = self.base + '/rest/wikis/xwiki/spaces/data/pages/' + patient_id + '/objects/' + object_class + '/' + object_num
        data = {}
        for key, value in object_obj.items():
            data['property#' + key] = value
        r = requests.put(url, auth=self.auth, data=data, verify=self.ssl_verify)
        r.raise_for_status()

    def set_owner(self, patient_id, owner):
        owner_name = PhenoTipsBot.qualify(owner)
        self.set_object(patient_id, 'PhenoTips.OwnerClass', '0', {'owner': owner})

    def set_pedigree(self, patient_id, pedigree_obj):
        #the SVG is not automatically updated if the JSON is changed via the REST API
        self.init_phantom()
        url = self.base + '/bin/' + patient_id + '?sheet=PhenoTips.PedigreeEditor'
        data = json.dumps(json.dumps(pedigree_obj, sort_keys=True))
        self.driver.get(url)
        self.driver.find_element_by_css_selector('#canvas svg') #wait for the page to load
        self.driver.execute_script('window.editor.getSaveLoadEngine().createGraphFromSerializedData(' + data + ');')
        self.driver.execute_script('window.editor.getSaveLoadEngine().save();')
        self.driver.find_element_by_css_selector('#action-save.menu-item') #wait for the image to be saved

    def set_relative(self, patient_id, relative_num, relative_obj):
        self.set_object(patient_id, 'PhenoTips.RelativeClass', relative_num, relative_obj)

    def set_study(self, patient_id, study):
        url = self.base + '/rest/wikis/xwiki/spaces/data/pages/' + patient_id + '/objects/PhenoTips.StudyBindingClass/0'
        r = requests.get(url, auth=self.auth, verify=self.ssl_verify)
        if r.status_code == 404:
            if study == None:
                return
            else:
                data = {'studyReference': PhenoTipsBot.qualify(study, 'Studies')}
                self.create_object(patient_id, 'PhenoTips.StudyBindingClass', data)
        else:
            r.raise_for_status()
            if study == None:
                requests.delete(url, auth=self.auth, verify=self.ssl_verify)
                r.raise_for_status()
            else:
                data = {'property#studyReference': PhenoTipsBot.qualify(study, 'Studies')}
                r = requests.put(url, auth=self.auth, data=data, verify=self.ssl_verify)
                r.raise_for_status()

    def set_vcf(self, patient_id, vcf_num, vcf_obj):
        self.set_object(patient_id, 'PhenoTips.VCF', vcf_num, vcf_obj)

    def upload_file(self, patient_id, filepath):
        fd = open(filepath, "rb")
        self.set_file(patient_id, basename(filepath), fd.read())
        fd.close()

    def qualify(pagename, namespace='XWiki'):
        if not pagename:
            return pagename
        if not '.' in pagename:
            pagename = namespace + '.' + pagename
        if not ':' in pagename:
            pagename = 'xwiki:' + pagename
        return pagename

    def unqualify(pagename, namespace='XWiki'):
        if pagename.startswith('xwiki:' + namespace + '.'):
            return pagename[len('xwiki:') + len(namespace) + len('.'):]
        if pagename.startswith('xwiki:'):
            return pagename[len('xwiki:'):]

class ApgarType:
    unknown = 'unknown'

class RelativeType:
    aunt_uncle = 'aunt_uncle'
    child = 'child'
    cousin = 'cousin'
    grandchild = 'grandchild'
    grandparent = 'grandparent'
    niece_nephew = 'niece_nephew'
    parent = 'parent'
    sibling = 'sibling'
    twin = 'twin'

class SexType:
    male = 'M'
    female = 'F'
    other = 'O'
