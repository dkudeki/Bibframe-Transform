import os, sys, requests, time, urllib, json, uuid, re, datetime, csv, threading
import HTMLParser
from lxml import etree
from unicodedata import normalize
from datetime import timedelta
from mysql.connector import MySQLConnection

class BrokenResponse:
	status_code = '404'

def sanitizeMatchString(match_string):
	if match_string[-1:] != '.' and match_string[-1:] != '-':
		return match_string
	else:
		return sanitizeMatchString(match_string[:-1])

def convertFillerURI(filler_uri,mode=None):
	if mode == 'person':
		prefix = 'http://catalogdata.library.illinois.edu/lod/entities/Persons/ht/'
	elif mode == 'subject':
		prefix = 'http://catalogdata.library.illinois.edu/lod/entities/Subjects/ht/'
	else:
		prefix = '_:b'
	print(filler_uri)
	base = filler_uri[filler_uri.rfind('/')+1:filler_uri.rfind('#')]
	end_string = filler_uri[filler_uri.rfind('#')+1:]
	if '-' in end_string:
		dash_index = end_string.rfind('-')
		end_string = end_string[:dash_index] + end_string[dash_index+1:]

	match = re.match(r"([a-zA-Z]+)([0-9]*)",end_string)
	if match:
		items = match.groups()
		if items[0] == 'Work':
			text_conversion = '0'
		elif items[0] == 'Instance':
			text_conversion = '1'
		elif items[0] == 'Agent':
			text_conversion = '2'
		elif items[0] == 'GenreForm':
			text_conversion = '3'
		else:
			text_conversion = '4'

		return prefix + base + text_conversion + items[1]
	else:
		return prefix + base

def createBlankNode(agent,mode=None):
	try:
		generated_blank_node = convertFillerURI(agent.xpath('./@rdf:about',namespaces={ "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#" })[0],mode)
		agent.set('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about',generated_blank_node)
		return generated_blank_node
	except IndexError:
		random_blank_node = '_:b' + str(uuid.uuid1().int)
		agent.set('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about',random_blank_node)
		return random_blank_node

def normalizeVariant(variant):
	if isinstance(variant,str):
		return variant.strip()
	elif isinstance(variant,unicode):
		return variant.encode('utf-8').strip()

def checkForError(error_case,result,url):
	if 'viaf.org' in url:
		return result.content.find(error_case) != 0
	else:
		return result.content.find(error_case) == -1

def getRequest(url,expectJSON,timesheet):
	local_start_time = datetime.datetime.now().time()

	if 'viaf.org' in url:
		timesheet_domain = 'viaf'
		try:
			h = HTMLParser.HTMLParser()
			splitpoint = url.find('?query=')+7
			url = url[:splitpoint] + h.unescape(url[splitpoint:])
			print(url)
		except UnicodeDecodeError:
			h = HTMLParser.HTMLParser()
			splitpoint = url.find('?query=')+7
			url = url[:splitpoint] + h.unescape(url[splitpoint:].decode('utf-8'))
			print(url)         
		except:
			raise

		error_case = '<'
	else:
		error_case = '<title>Temporarily out of service</title>'
		if 'worldcat' in url:
			timesheet_domain = 'worldcat'
		else:
			timesheet_domain = 'loc'

	print(url)
	try:
		result = requests.get(url,timeout=60)
		if expectJSON:
			check_json = result.json()
	except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, ValueError) as e:
		try:
			if result:
				print(result.status_code)
		except:
			result = BrokenResponse()

	if result.status_code == 403:
		local_end_time = datetime.datetime.now().time()
		timesheet[timesheet_domain]['calls'] += 1
		duration = datetime.datetime.combine(datetime.date.min,local_end_time)-datetime.datetime.combine(datetime.date.min,local_start_time)
		if duration >= timedelta(0):
			timesheet[timesheet_domain]['time'] += duration
		else:
			timesheet[timesheet_domain]['time'] += (timedelta(days=1) + duration)
		return None

	print(url)
	try:
		if result.status_code == 200 and checkForError(error_case,result,url):
			retry = False
		else:
			retry = True
	except:
		retry = True

	while retry:
		print(result.status_code)
		time.sleep(6)
		try:
			result = requests.get(url,timeout=60)
			if expectJSON:
				check_json = result.json()
		except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, ValueError) as e:
			try:
				if result:
					print(result.status_code)
			except:
				result = BrokenResponse()

		try:
			if result.status_code == 200 and checkForError(error_case,result,url):
				retry = False
		except:
			pass

	print(result.content)
	print(result.content.find(error_case))
	local_end_time = datetime.datetime.now().time()
	timesheet[timesheet_domain]['calls'] += 1
	duration = datetime.datetime.combine(datetime.date.min,local_end_time)-datetime.datetime.combine(datetime.date.min,local_start_time)
	if duration >= timedelta(0):
		timesheet[timesheet_domain]['time'] += duration
	else:
		timesheet[timesheet_domain]['time'] += (timedelta(days=1) + duration)
	return result

#Sets @rdf:about for bf:Work and @rdf:resource for bf:Instance/bf:instanceOf to the instance's OCLC record's 'exampleOfWork' value
def setWorkURLs(work,instance,placeholder_work_id,instance_url,last_loaded_worldcat_record,timesheet):
	if last_loaded_worldcat_record is None or last_loaded_worldcat_record['url'] != instance_url:
		if 'worldcat.org' in instance_url:
			result = getRequest(instance_url + '.jsonld',True,timesheet)
#            result = requests.get(instance_url + '.jsonld')
#            while result.status_code != 200:
#                print(result.status_code)
#                time.sleep(6)
#                try:
#                    result = requests.get(instance_url + '.jsonld')
#                except requests.exceptions.ConnectionError:
#                    result = { 'status_code': '404' }

			if result:
#				print(result.content)
				print(len(result.content))
				try:
					result = result.json()
				except:
					print(result.content)
					print(instance_url)
					sys.exit()
#				print(result['@graph'])
				print(len(result['@graph']))
				for r in result['@graph']:
					if 'exampleOfWork' in r:
						work.set('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about',r['exampleOfWork'])
						instance.xpath("./bf:instanceOf[@rdf:resource='" + placeholder_work_id + "']", namespaces={ "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#", "bf": "http://id.loc.gov/ontologies/bibframe/" })[0].set("{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource",r['exampleOfWork'])

				return { 'url': instance_url, 'record': result }
			else:
				return None
		else:
			work.set('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about', instance_url + "1")
			instance.xpath("./bf:instanceOf[@rdf:resource='" + placeholder_work_id + "']", namespaces={ "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#", "bf": "http://id.loc.gov/ontologies/bibframe/" })[0].set("{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource",instance_url + "1")
			return None
	else:
		print("BENEFIT")
		for r in last_loaded_worldcat_record['record']['@graph']:
			if 'exampleOfWork' in r:
				work.set('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about',r['exampleOfWork'])
				instance.xpath("./bf:instanceOf[@rdf:resource='" + placeholder_work_id + "']", namespaces={ "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#", "bf": "http://id.loc.gov/ontologies/bibframe/" })[0].set("{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource",r['exampleOfWork'])

		return last_loaded_worldcat_record

def getAgentTypes(agent_types,target_domain):
	if 'http://id.loc.gov/ontologies/bibframe/Organization' in agent_types:
		return ('CorporateName' if target_domain == 'id.loc.gov' else 'corporate'), 'name10MatchKey', 'subjects'
	elif 'http://id.loc.gov/ontologies/bibframe/Person' in agent_types or 'http://www.loc.gov/mads/rdf/v1#Name' in agent_types:
		return ('PersonalName' if target_domain == 'id.loc.gov' else 'personal'), 'name00MatchKey', 'names'
	elif 'http://id.loc.gov/ontologies/bibframe/Meeting' in agent_types or 'http://www.loc.gov/mads/rdf/v1#ConferenceName' in agent_types:
		return ('ConferenceName' if target_domain == 'id.loc.gov' else 'corporate'), 'name11MatchKey', 'names'
	elif 'http://id.loc.gov/ontologies/bibframe/Jurisdiction' in agent_types:
		return ('CorporateName' if target_domain == 'id.loc.gov' else 'corporate'), 'name10MatchKey', 'names'
	elif 'http://id.loc.gov/ontologies/bibframe/Family' in agent_types:
		return ('FamilyName' if target_domain == 'id.loc.gov' else 'personal'), 'name00MatchKey', 'subjects'
	elif 'http://www.loc.gov/mads/rdf/v1#Topic' in agent_types:
		return 'Topic', 'authoritativeLabel', 'subjects'
	elif 'http://www.loc.gov/mads/rdf/v1#Geographic' in agent_types:
		return 'Geographic', 'authoritativeLabel', 'subjects'
	elif 'http://www.loc.gov/mads/rdf/v1#Title' in agent_types:
		return 'Title', 'authoritativeLabel', 'names'
	elif 'http://www.loc.gov/mads/rdf/v1#NameTitle' in agent_types:
		return 'NameTitle', 'authoritativeLabel', 'names'
	elif 'http://www.loc.gov/mads/rdf/v1#HierarchicalGeographic' in agent_types:
		return 'ComplexSubject', 'label', 'subjects'
	elif agent_types[0] == 'http://www.loc.gov/mads/rdf/v1#ComplexSubject':
		return 'ComplexSubject', 'authoritativeLabel', 'subjects'
	else:
		print("FOUND UNHANDLED SUBJECT TYPE:")
		print(agent_types)
		sys.exit()

def searchLOC(agent,cursor,connection,match_key,agent_type,search_type,timesheet):
	BASE_LC_URL = 'https://id.loc.gov/search/?q='
	query_url = BASE_LC_URL + urllib.quote_plus(match_key) + '+rdftype:' + agent_type + '&q=cs%3Ahttp%3A%2F%2Fid.loc.gov%2Fauthorities%2F' + search_type
	print(query_url)

	results_tree = etree.HTML(getRequest(query_url,False,timesheet).content)
	result_table = results_tree.xpath("//table[@class='id-std']/tbody/tr")
	match_not_found = True
	i = 0
	while i < len(result_table) and match_not_found:
		authorized_heading = result_table[i].xpath("./td/a/text()")
		print(authorized_heading)
		variant_headings = result_table[i+1].xpath("./td[@colspan='4']/text()")
		print(variant_headings)
		if len(variant_headings) > 0:
			variant_headings = map(normalizeVariant,variant_headings[0].split(';'))
		print(variant_headings)
		print(match_key, authorized_heading[0])
		print(match_key == authorized_heading[0])

		if match_key in authorized_heading or match_key in variant_headings:
			print("Found " + match_key)
			subject_uri = 'http://id.loc.gov' + result_table[i].xpath("./td/a/@href")[0]
			print(subject_uri)
			agent.set('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about',subject_uri)
			match_not_found = False

			cursor.execute(u'SELECT * FROM Subject WHERE url = %s',(subject_uri,))
			if not cursor.rowcount:
				add_subject = u'INSERT INTO Subject (url, label, concept_type) VALUES (%s, %s, %s)'
				subject_data = (subject_uri,authorized_heading[0].encode('utf-8'),'http://www.loc.gov/mads/rdf/v1#' + agent_type)
				print(subject_data)
				print(type(subject_uri))
				print(type(authorized_heading[0].encode('utf-8')))
				print(type('http://www.loc.gov/mads/rdf/v1#' + agent_type))
				cursor.execute(add_subject,subject_data)
				connection.commit()
			else:
				cursor.execute(u'INSERT INTO Variant_Name (url, variant_name) VALUES (%s, %s)',(subject_uri,authorized_heading[0].encode('utf-8')))
				connection.commit()

			add_variant_name = u'INSERT INTO Variant_Name (url, variant_name) VALUES (%s, %s)'
			for variant in variant_headings:
				variant_data = (subject_uri,variant)
				print(variant_data)
				cursor.execute(add_variant_name,variant_data)
				connection.commit()

			if agent_type == 'ComplexSubject' and match_key in authorized_heading:
				components_uri = subject_uri + '.madsrdf.rdf'
				print(components_uri)

				component_tree = etree.fromstring(getRequest(components_uri,False,timesheet).content)
				component_list = component_tree.xpath("/rdf:RDF/madsrdf:ComplexSubject/madsrdf:componentList/*",namespaces={ "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#", "madsrdf": "http://www.loc.gov/mads/rdf/v1#" })
				print("Component List:")
				print(component_list)

				output_component_list = agent.xpath("./madsrdf:componentList/*",namespaces={ "madsrdf": "http://www.loc.gov/mads/rdf/v1#" })
				print("Output Component List:")
				print(output_component_list)

				add_component = u'INSERT INTO Component (source_url, sequence_value, component_url) VALUES (%s, %s, %s)'

				j = 0
				while j < len(component_list):
					component_url = component_list[j].xpath("./@rdf:about",namespaces={ "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#" })
					if component_url:
						cursor.execute('SELECT * FROM Component WHERE source_url = %s',(subject_uri,))
						if not cursor.rowcount:
							component_data = (subject_uri,j,component_url[0].encode('utf-8'))
							print(component_data)
							print(type(subject_uri))
							print(type(j))
							print(type(component_url[0].encode('utf-8')))
							cursor.execute(add_component,component_data)
							connection.commit()
						output_component_list[j].set('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about',component_url[0])
					j = j + 1
		i = i + 2

	if match_not_found:
		new_blank_node = createBlankNode(agent,'subject')
		add_subject = u'INSERT INTO Subject (url, label, concept_type) VALUES (%s, %s, %s)'
		print(new_blank_node)
		print(match_key)
		subject_data = (new_blank_node,match_key,'http://www.loc.gov/mads/rdf/v1#' + agent_type)
		cursor.execute(add_subject,subject_data)
		connection.commit()

def getLOCID(agent,cursor,connection,match_key,agent_type,search_type,timesheet):
	found_loc_url = False
	loc_url = None

	print(match_key)
	print('http://www.loc.gov/mads/rdf/v1#' + agent_type)
	cursor.execute('SELECT * FROM Subject WHERE label = %s AND concept_type = %s',(match_key, 'http://www.loc.gov/mads/rdf/v1#' + agent_type))
	for table in cursor:
		print(table[0])
		loc_url = table[0]
		agent.set('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about',loc_url)
		found_loc_url = True

	if not found_loc_url:
		cursor.execute('SELECT * FROM Variant_Name WHERE variant_name = %s',(match_key,))
		for table in cursor:
			loc_url = table[0]
			agent.set('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about',loc_url)
			found_loc_url = True

	if found_loc_url:
		if agent_type == 'ComplexSubject':
			output_component_list = agent.xpath("./madsrdf:componentList/*",namespaces={ "madsrdf": "http://www.loc.gov/mads/rdf/v1#" })
			print("Output Component List:")
			print(output_component_list)

			if output_component_list:
				cursor.execute('SELECT * FROM Component INNER JOIN Subject ON Component.component_url = Subject.url WHERE source_url = %s',(loc_url,))
				for table in cursor:
					print(table)
#							print(type(str(output_component_list[table[1]].xpath('./*/text()')[0])))
					if table[1] < len(output_component_list) and table[4] == output_component_list[table[1]].xpath('./*/text()')[0].encode('utf-8'):
						output_component_list[table[1]].set('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about',table[2])
	else:
		searchLOC(agent,cursor,connection,match_key,agent_type,search_type,timesheet)

#Search id.loc.gov for an exact subject match, assign the url of that subject to bf:Agent/@rdf:about, remember subjects that have been 
#   retrieved in a dictionary that can be referenced instead of redundantly calling id.loc.gov again
def setSubjectAgent(agent,cursor,connection,timesheet):
	agent_types = agent.xpath("./rdf:type/@rdf:resource",namespaces={ "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#" })
	agent_type = None
	if agent_types:
		agent_type, match_key_type, search_type = getAgentTypes(agent_types,'id.loc.gov')

	print('V---SUBJECT AGENT--SUBJECT AGENT--SUBJECT AGENT--SUBJECT AGENT--SUBJECT AGENT----V')
	if agent_type:
		match_key = agent.xpath("./bflc:" + match_key_type + "/text()", namespaces={ "bflc": "http://id.loc.gov/ontologies/bflc/" })
		if len(match_key) > 0:
			match_key = match_key[0]
		else:
			match_key = agent.xpath("./rdfs:label/text()", namespaces={ "rdfs": "http://www.w3.org/2000/01/rdf-schema#" })
			if len(match_key) > 0:
				match_key = match_key[0]
			else:
				match_key = None

		if match_key:
			match_key = sanitizeMatchString(match_key.encode('utf-8'))

			if len(match_key) > 200:
				match_key = shortenMatchKey(agent,match_key,match_key_type,'bflc','http://id.loc.gov/ontologies/bflc/')

			getLOCID(agent,cursor,connection,match_key,agent_type,search_type,timesheet)
		else:
			new_blank_node = createBlankNode(agent,'subject')
			add_subject = u'INSERT INTO Subject (url, label, concept_type) VALUES (%s, %s, %s)'
			subject_data = (new_blank_node,None,'http://www.loc.gov/mads/rdf/v1#' + agent_type)
			cursor.execute(add_subject,subject_data)
			connection.commit()

	print('^---SUBJECT AGENT--SUBJECT AGENT--SUBJECT AGENT--SUBJECT AGENT--SUBJECT AGENT----^')

def shortenMatchKey(agent,match_key,match_key_type,namespace,namespace_value):
	new_match_key_type = match_key_type.replace('Match','Marc')
	new_match_key = agent.xpath("./" + namespace + ":" + new_match_key_type + "/text()", namespaces={ namespace: namespace_value })
	if len(new_match_key) > 0:
		new_match_key = new_match_key[0]
		new_match_key = new_match_key[new_match_key.find('$a')+2:]
		new_match_key = new_match_key[:new_match_key.find("$")]
		new_match_key = sanitizeMatchString(new_match_key.replace('"','\\\"').encode('utf-8'))
		if len(new_match_key) <= 200:
			return new_match_key
		else:
			return match_key[:200]
	else:
		return match_key[:200]

def setTopicAgent(agent,cursor,connection,timesheet):
	agent_types = agent.xpath("./rdf:type/@rdf:resource",namespaces={ "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#" })
	agent_type = None
	if agent_types:
		agent_type, match_key_type, search_type = getAgentTypes(agent_types,'id.loc.gov')

	print('V--TOPIC--TOPIC--TOPIC--TOPIC--TOPIC--TOPIC--TOPIC--TOPIC--TOPIC--TOPIC--TOPIC---V')
	if agent_type:
		match_key = agent.xpath("./madsrdf:" + match_key_type + "/text()", namespaces={ "madsrdf": "http://www.loc.gov/mads/rdf/v1#" })
		if len(match_key) > 0:
			match_key = match_key[0]
		else:
			match_key = agent.xpath("./rdfs:label/text()", namespaces={ "rdfs": "http://www.w3.org/2000/01/rdf-schema#" })
			if len(match_key) > 0:
				match_key = match_key[0]
			else:
				match_key = None

		if match_key:
			match_key = sanitizeMatchString(match_key.replace('"','\\\"').encode('utf-8'))
			print(match_key)

			if len(match_key) > 200:
				match_key = shortenMatchKey(agent,match_key,match_key_type,'madsrdf','http://www.loc.gov/mads/rdf/v1#')

			getLOCID(agent,cursor,connection,match_key,agent_type,search_type,timesheet)
		else:
			new_blank_node = createBlankNode(agent,'subject')
			add_subject = u'INSERT INTO Subject (url, label, concept_type) VALUES (%s, %s, %s)'
			subject_data = (new_blank_node,None,'http://www.loc.gov/mads/rdf/v1#' + agent_type)
			cursor.execute(add_subject,subject_data)
			connection.commit()

	print('^--TOPIC--TOPIC--TOPIC--TOPIC--TOPIC--TOPIC--TOPIC--TOPIC--TOPIC--TOPIC--TOPIC---^')

def setContributionAgent(agent,countries,cursor,connection,timesheet):
	agent_types = agent.xpath("./rdf:type/@rdf:resource",namespaces={ "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#" })
	agent_type = None
	if agent_types:
		agent_type, match_key_type, search_type = getAgentTypes(agent_types,'viaf.org')

	print('V-CONTRIBUTION AGENT--CONTRIBUTION AGENT--CONTRIBUTION AGENT--CONTRIBUTION AGENT-V')
	if agent_type:
		match_key = agent.xpath("./bflc:" + match_key_type + "/text()", namespaces={ "bflc": "http://id.loc.gov/ontologies/bflc/" })
		if len(match_key) > 0:
			match_key = match_key[0]
		else:
			match_key = agent.xpath("./rdfs:label/text()", namespaces={ "rdfs": "http://www.w3.org/2000/01/rdf-schema#" })
			if len(match_key) > 0:
				match_key = match_key[0]
			else:
				match_key = None

		if match_key:
			match_key = sanitizeMatchString(match_key.replace('\\','\\\\').encode('utf-8'))
			print(match_key)
			if len(match_key) > 200:
				match_key = shortenMatchKey(agent,match_key,match_key_type,'bflc','http://id.loc.gov/ontologies/bflc/')

			if match_key in countries:
				agent.set('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about',countries[match_key])
			else:
				found_agent_url = False
				found_agent_authorized = False
				found_authorized_count = 0
				agent_url = None

				find_name_in_found = u'SELECT url FROM found_names WHERE label = %s AND type = %s'
				cursor.execute(find_name_in_found,(match_key,agent_type))
				if cursor.rowcount != 0:
					found_agent_url = True
					rows = cursor.fetchall()
					agent_url = rows[0][0]

				if found_agent_url:
					agent.set('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about',agent_url)
				else:
					find_name_in_stored = u'SELECT * FROM stored_names WHERE label = %s AND type = %s LIMIT 100'
#					find_best_name = u'SELECT target.url, target.label, target.class, target.type , COUNT(*) AS count FROM names JOIN (SELECT * FROM names WHERE label = %s AND type = %s) as target WHERE names.url = target.url GROUP BY target.url, target.label, target.class, target.type ORDER BY class DESC, count DESC LIMIT 1'
#					find_name = u'SELECT * FROM names WHERE label = %s LIMIT 100'
					cursor.execute(find_name_in_stored,(match_key,agent_type))
					#If only one authorized agent, choose that; if zero authorized agents, search; if more than one authorized agent, mint a new uri
					for table in cursor:
						if table[2] == 'authorized':
							found_authorized_count = 1 + found_authorized_count

							if not found_agent_authorized:
								agent_url = table[1]
								found_agent_url = True

							found_agent_authorized = True

						if not found_agent_url:
							found_agent_url = True
							agent_url = table[1]

					if found_agent_url and found_authorized_count == 1:
						agent.set('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about',agent_url)
					elif found_authorized_count > 1:
						new_uri = createBlankNode(agent,'person')
						add_name = u'INSERT INTO found_names (label, url, type) VALUES (%s, %s, %s)'
						name_data = (normalize('NFC',match_key.decode('utf-8')),new_uri,agent_type)
						cursor.execute(add_name,name_data)
						connection.commit()
					else:
						BASE_VIAF_URL = 'http://www.viaf.org/viaf/AutoSuggest?query='
						query_url = BASE_VIAF_URL + match_key.replace('"',"'")
			#            results = requests.get(query_url).content
						results = getRequest(query_url,True,timesheet).content
						print(match_key)
						print(query_url)
						print(results)

						match_not_found = True

						try:
							results_dict = json.loads(results)
							print(results_dict)
							if results_dict['result']:
								i = 0
								while i < len(results_dict['result']) and match_not_found:
									print(results_dict['result'][i]['term'] == match_key.decode('utf-8'))
									print(results_dict['result'][i]['term'])
									print(match_key.decode('utf-8'))
									print(sanitizeMatchString(normalize('NFC',results_dict['result'][i]['term'])) == normalize('NFC',match_key.decode('utf-8')))
									if results_dict['result'][i]['nametype'] == agent_type and sanitizeMatchString(normalize('NFC',results_dict['result'][i]['term'])) == normalize('NFC',match_key.decode('utf-8')) and 'viafid' in results_dict['result'][i]:
										print("Found " + match_key)
										agent_uri = "http://www.viaf.org/viaf/" + results_dict['result'][i]['viafid']
										print(agent_uri)
										agent.set('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about',agent_uri)
										match_not_found = False
										print(agent_type)

										add_name = u'INSERT INTO found_names (label, url, type) VALUES (%s, %s, %s)'
										name_data = (normalize('NFC',match_key.decode('utf-8')),agent_uri,agent_type)
										cursor.execute(add_name,name_data)
										connection.commit()

									i = i + 1
						except:
							pass

						if match_not_found:
							new_uri = createBlankNode(agent,'person')
							add_name = u'INSERT INTO found_names (label, url, type) VALUES (%s, %s, %s)'
							name_data = (normalize('NFC',match_key.decode('utf-8')),new_uri,agent_type)
							cursor.execute(add_name,name_data)
							connection.commit()
		else:
			createBlankNode(agent)

	print('^-CONTRIBUTION AGENT--CONTRIBUTION AGENT--CONTRIBUTION AGENT--CONTRIBUTION AGENT-^')

def getWorldCatData(works,work_ids,timesheet):
	for work in works:
		placeholder_work_id = work.xpath("./@rdf:about", namespaces={ "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#" })[0]
		instances = root.xpath("/rdf:RDF/bf:Instance[bf:instanceOf/@rdf:resource='" + placeholder_work_id + "']", namespaces={ "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#", "bf": "http://id.loc.gov/ontologies/bibframe/" })[0]
		instance_url = instances.xpath("@rdf:about", namespaces={ "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#" })[0]

		try:
			print(work_ids[instance_url])
		except:
			if 'worldcat.org' in instance_url:
				result = getRequest(instance_url + '.jsonld',True,timesheet)

				if result:
#					print(result.content)
					print(len(result.content))
					try:
						result = result.json()
					except:
						print(result.content)
						print(instance_url)
						sys.exit()
#					print(result['@graph'])
					print(len(result['@graph']))
					for r in result['@graph']:
						if 'exampleOfWork' in r:
							work_ids[instance_url] = r['exampleOfWork']
				else:
					work_ids[instance_url] = instance_url + "1"
			else:
				work_ids[instance_url] = instance_url + "1"

def postConversionTransform(file_name):
	start_time = datetime.datetime.now().time()

	with open('viaf_countries.json','r') as readfile:
		countries = json.load(readfile)

	connection = MySQLConnection(user='root',password='',database='subjects')
	cursor = connection.cursor(buffered=True)

	names_connection = MySQLConnection(user='root',password='',database='names')
	names_cursor = names_connection.cursor(buffered=True)
	print(file_name)
	tree = etree.parse(file_name)
	root = tree.getroot()

	works = root.xpath('/rdf:RDF/bf:Work', namespaces={ "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#", "bf": "http://id.loc.gov/ontologies/bibframe/" })
	print(len(works))
	print(works)

	last_loaded_worldcat_record = None

	timesheet = { 'worldcat': { 'calls': 0, 'time': timedelta(0) }, 'loc': { 'calls': 0, 'time': timedelta(0) }, 'viaf': { 'calls': 0, 'time': timedelta(0) } }

#	work_ids = {}
#	getWorldCatData(works,work_ids,timesheet)

	for work in works:
		print('V-WORK--WORK--WORK--WORK--WORK--WORK--WORK--WORK--WORK--WORK--WORK--WORK--WORK--WORK-V')
		placeholder_work_id = work.xpath("./@rdf:about", namespaces={ "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#" })[0]
		instances = root.xpath("/rdf:RDF/bf:Instance[bf:instanceOf/@rdf:resource='" + placeholder_work_id + "']", namespaces={ "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#", "bf": "http://id.loc.gov/ontologies/bibframe/" })
		instance_url = instances[0].xpath("@rdf:about", namespaces={ "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#" })[0]

		print(instance_url + '.jsonld')
		last_loaded_worldcat_record = setWorkURLs(work,instances[0],placeholder_work_id,instance_url,last_loaded_worldcat_record,timesheet)

		subject_agents = work.xpath("./bf:subject/bf:Agent",namespaces={ "bf": "http://id.loc.gov/ontologies/bibframe/" })
		for agent in subject_agents:
			setSubjectAgent(agent,cursor,connection,timesheet)

		print("Starting Topics")
		topic_agents = work.xpath("./bf:subject/*[not(self::bf:Agent or self::bf:Temporal)]",namespaces={ "bf": "http://id.loc.gov/ontologies/bibframe/" })
		print(topic_agents)
		for t_agent in topic_agents:
			setTopicAgent(t_agent,cursor,connection,timesheet)

		print("Starting Contribution Agents")
		contribution_agents = work.xpath("./bf:contribution/bf:Contribution/bf:agent/bf:Agent",namespaces={ "bf": "http://id.loc.gov/ontologies/bibframe/" })
		print(contribution_agents)
		for c_agent in contribution_agents:
			setContributionAgent(c_agent,countries,names_cursor,names_connection,timesheet)
		print('^-WORK--WORK--WORK--WORK--WORK--WORK--WORK--WORK--WORK--WORK--WORK--WORK--WORK--WORK-^')

	cursor.close()
	connection.close()

	example_agents = root.xpath(".//*[contains(@*,'example.org')]")
#	print(example_agents)
	print("Number of example.org urls converted: " + str(len(example_agents)))
	for e_a in example_agents:
		print(e_a)
		print(e_a.xpath('@*')[0])
		print(e_a.xpath('name(@*[1])'))
		print(convertFillerURI(e_a.xpath('@*')[0]))
		blank_node = convertFillerURI(e_a.xpath('@*')[0])
#		placeholder_value = e_a.xpath('@*')[0]
#		if '-' in placeholder_value:
#			blank_node = convertFillerURI(e_a.xpath('@*')[0])
#		else:
#			blank_node = '_:b' + placeholder_value[placeholder_value.rfind('/')+1:placeholder_value.rfind('#')]
#			print(blank_node)
		full_attribute_name = e_a.xpath('name(@*[1])')
		print('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}' + full_attribute_name[full_attribute_name.rfind(':')+1:])
		e_a.set('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}' + full_attribute_name[full_attribute_name.rfind(':')+1:],blank_node)
		print(e_a.xpath('@*')[0])

#	print(merged_subject_agents)
#	print("Number of unique subject agents: " + str(len(merged_subject_agents)))
#	print("Number of unique contribution agents: " + str(len(merged_contribution_agents)))
#	print("Number of unique topics: " + str(len(merged_topic_agents)))

	with open(file_name,'w') as outfile:
		outfile.write(etree.tostring(tree))

	end_time = datetime.datetime.now().time()

	with open('bibframe_transform_timesheet.csv','a') as timesheet_file:
		duration = datetime.datetime.combine(datetime.date.min,end_time)-datetime.datetime.combine(datetime.date.min,start_time)

		if duration < timedelta(0):
			duration += timedelta(days=1)

		output_array = [file_name[file_name.rfind('/')+1:],duration,duration/10000,timesheet['worldcat']['calls'],timesheet['worldcat']['time'],(timesheet['worldcat']['time']/timesheet['worldcat']['calls'] if timesheet['worldcat']['calls'] > 0 else timesheet['worldcat']['time']),timesheet['loc']['calls'],timesheet['loc']['time'],(timesheet['loc']['time']/timesheet['loc']['calls'] if timesheet['loc']['calls'] > 0 else timesheet['loc']['time']),timesheet['viaf']['calls'],timesheet['viaf']['time'],(timesheet['viaf']['time']/timesheet['viaf']['calls'] if timesheet['viaf']['calls'] > 0 else timesheet['viaf']['time'])]

		writer = csv.writer(timesheet_file, delimiter=',')
		writer.writerow(output_array)