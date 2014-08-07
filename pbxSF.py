#! /usr/bin/env python
import sys, getopt, telnetlib, re, socket, time, datetime, pytz, threading, Queue, SimpleHTTPServer, urlparse, SocketServer, pickle, os, ssl, base64, logging
from pbxSF_config import *
from simple_salesforce import Salesforce
from encryptedpickle import encryptedpickle
logging.basicConfig(format='%(asctime)s %(message)s', level=logging.DEBUG)

class server(threading.Thread):
    def __init__(self,):
        threading.Thread.__init__(self)
    def run(self):
        logging.info("SERVER started on port " + str(port))
        Handler = MyHandler
        httpd = SocketServer.TCPServer(("", port), Handler)
        httpd.serve_forever()
        logging.info("Exiting SERVER")
        
class MyHandler(SimpleHTTPServer.SimpleHTTPRequestHandler):

	def do_HEAD(self):
		"""
		Send HTML Header.
		"""
		logging.info("send header")
		self.send_response(200)
		self.send_header('Content-type', 'text/html')
		self.end_headers()

	def do_AUTHHEAD(self, realm):
		"""
		Request HTTP Authentication from client.
		"""
		logging.info("send header")
		self.send_response(401)
		self.send_header('WWW-Authenticate', 'Basic realm=\"' + realm + '\"')
		self.send_header('Content-type', 'text/html')
		self.end_headers()

	def do_GET(self):
		"""
		Serve regular requests.
		"""
		# Load global names
		global authKey
		global whitelistLogging
		global sharedUsers
		global unansweredEnabled
		global loggingEnabled
		global voicemailEnabled
		global showMessage

		# Time request
		starttime = time.time()
		authorised = False

		# Present frontpage with user authentication, if key set in config; otherwise ask for key!
		try:
			if authKey:
				logging.info("HTTP authentication requested.")
				if self.headers.getheader('Authorization') == None:
					self.do_AUTHHEAD(realm="pbxSF login")
					self.wfile.write('no auth header received')
					pass
				elif self.headers.getheader('Authorization') == 'Basic ' + authKey:
					logging.info("HTTP Authorised.")
					authorised = True
				else:
					# If not authenticated
		 			self.do_AUTHHEAD(realm="pbxSF login")
					self.wfile.write(self.headers.getheader('Authorization'))
					self.wfile.write(' not authenticated')
					pass
		except:
			logging.info("Request user to set HTTP auth details.")
			if not self.headers.getheader('Authorization'):
				self.do_AUTHHEAD(realm="First time run: Please enter the log in you would like to use for the webinterface.")
			else:
				if self.headers.getheader('Authorization') == None:
					self.wfile.write('no auth header received')
				else:
					authKey = self.headers.getheader('Authorization').strip('Basic ')
					showMessage.add("Your log-in details have been saved!")
					logging.info("HTTP auth details set.")
					logging.info("HTTP Authorised.")
					authorised = True

		if authorised == True:
			# Analyse HTTP GET content
			qs = {}
			path = self.path
			if '?' in path:
				path, tmp = path.split('?', 1)
				qs = urlparse.parse_qs(tmp)
			logging.info("Path: " + path)
			
			# Print GET content
			dict_print = ""
			for key, value in qs.items():
				dict_print += "{} : {}".format(key, value) # for debug/log
				dict_print += " | "

			# Update active extensions
			if 'whitelist' in qs:
				whitelistLogging = tuple(qs['whitelist'])

			# Delete Shared User
			if 'deleteUser' in qs:
				for userId in qs['deleteUser']:
					if userId in sharedUsers:
						del sharedUsers[userId]
						showMessage.add("Shared User deleted.")

			# Save config (encrypted)
			if ('savename' in qs) and ('savesecret' in qs):
				if len(qs['savesecret'][0]) >= 8:
					saveData((sharedUsers, whitelistLogging, unansweredEnabled, loggingEnabled, voicemailEnabled, authKey), qs['savename'][0] + ".epk", {0: qs['savesecret'][0]*4})
					logging.info("Config saved as " + qs['savename'][0] + ".epk")
					showMessage.add("Config saved as '" + qs['savename'][0] + "'.")
				else:
					showMessage.add("Passphrase too short - needs to be at least 8 characters")
					logging.warning("Passphrase too short - needs to be at least 8 characters")

			# Load config (encrypted)
			if ('loadname' in qs) and ('loadsecret' in qs):
				data = loadData(qs['loadname'][0] + ".epk", qs['loadsecret'][0]*4)
				if data:
					if len(data) == 6:
						sharedUsers = data[0]
						whitelistLogging = data[1]
						unansweredEnabled = data[2]
						loggingEnabled = data[3]
						voicemailEnabled = data[4]
						authKey = data[5]
						showMessage.add("Config loaded succesfully.")
					else:
						showMessage.add("Config could not be loaded: Format incompatible.")
				else:
					showMessage.add("Config could not be loaded: File not found or passphrase wrong.")

			# Enable/Disable logging of unanswered calls
			if 'unanswered' in qs:
				if qs['unanswered'][0] == 'disable':
					unansweredEnabled = False
				elif qs['unanswered'][0] == 'enable':
					unansweredEnabled = True

			# Enable/Disable logging of calls gone to voicemail
			if 'voicemail' in qs:
				if qs['voicemail'][0] == 'disable':
					voicemailEnabled = False
				elif qs['voicemail'][0] == 'enable':
					voicemailEnabled = True

			# Enable/Disable logging
			if 'loggingEnabled' in qs:
				if qs['loggingEnabled'][0] == 'disable':
					loggingEnabled = False
				elif qs['loggingEnabled'][0] == 'enable':
					loggingEnabled = True

			# Add Shared User
			if 'addUser' in qs:
				for userId in qs['addUser']:
					if not userId in sharedUsers: # only if user not added as shared user, yet
						sharedUsers[userId] = []
						showMessage.add("Shared User added.")

			# All user IDs in SalesForce begin with 005, so if there is a key beginning with 005, we assume it's a sharedUser and update the entry accordingly.
			sharedUsersGet = sliceDict(qs, '005')
			for sharedUserGet in sharedUsersGet:
				sharedUsers[sharedUserGet] = sharedUsersGet[sharedUserGet]

			# Redirect to / if any GET arguments sent (and processed), so user don't accidentally refresh with same arguments.
			if len(qs) > 0: # if any GET argumentst
				self.send_response(302)
				self.send_header("Location", "/")
				self.end_headers()
			else:
				# Generate webpage
				# Send HTTP 200 Header
				self.send_response(200, 'OK')
				self.send_header('Content-type', 'text/html')
				self.end_headers()

				# HTML holds and collects content of webpage until transmission
				html = """
				<!doctype html>
				<html>
					<head>
						<meta charset="UTF-8">
						<meta name="viewport" content="width=device-width, initial-scale=1">
						<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
						<link rel="stylesheet" href="//maxcdn.bootstrapcdn.com/bootstrap/3.2.0/css/bootstrap.min.css">
						<link rel="stylesheet" href="//maxcdn.bootstrapcdn.com/bootstrap/3.2.0/css/bootstrap-theme.min.css">
						<script src="//netdna.bootstrapcdn.com/bootstrap/3.1.1/js/bootstrap.min.js"></script>
						<script src="//code.jquery.com/jquery-1.11.0.min.js"></script>
						<script src="//code.jquery.com/jquery-migrate-1.2.1.min.js"></script>
						<title>PBXsf</title>
					</head>
					<body style="width:95%;margin-left:auto;margin-right:auto;">
					<div class="page-header">
						<h1>PBXsf <small>Logging FreePBX calls in SalesForce</small></h1>
					</div>"""
				for i in range(len(showMessage)):
					html += '<div class="alert alert-info" role="alert">' + str(showMessage.pop()) + '</div>'
				html += """<div style="width:80%;margin-left:auto;margin-right:auto;">
						<!--White List-->
						<div class="panel panel-default" style="height:450px;float:left;width:250px;margin:5px;">
							<div class="panel-heading">Active Users<br /><small>Additionally to the Shared Users</small></div>
							<div class="panel-body">
							<form role="form" action="/" autocomplete="off" method="GET" >
							<div class="form-group">
							<select class="form-control" name="whitelist" multiple="multiple" style="height:300px;width=90%">"""
				# save current data from SF and freePBX for access throughout processing of the request
				extensions = sorted(getAllExtensions().iteritems(), key=lambda (k,v): v) # Sort by value (Name; put "k" to sort by the key, the extension)
				activeUsers = getActiveUsers()
				activeUsersNames = getUsersNames(activeUsers)
				
				# Get active extensions and mark them as "selected" in the form.
				for extension in extensions:
					if extension[1] in activeUsersNames:
						html += '<option value="' + extension[0]
						if extension[0] in whitelistLogging:
							html += '" selected="selected">'
						else:
							html += '">'
						html += extension[0] + ": " + extension[1] + "</option>"
				html += """
							</select><br />
							<button type="submit" class="btn btn-primary" style="margin:5px;">Update</button>
							</div>
							</form>
							</div>
						</div>"""
				# Get all configured shared user and generate panel with all extensions to assign to the shared user
				for sharedUser in sharedUsers:
					html += """<div class="panel panel-default" style="height:450px;float:left;width:250px;overflow:hidden;margin:5px;">
							<div class="panel-heading">Shared User: """ + activeUsers[sharedUser]['Username'] + """</div>
							<div class="panel-body">
							<form role="form" action="/" autocomplete="off" method="GET" >
							<div class="form-group">
							<select class="form-control" name=""" + '"' + sharedUser + '" multiple="multiple" style="height:300px;width=90%">'
					extensions = sorted(getAllExtensions().iteritems(), key=lambda (k,v): v) # Sort by value (Name; put "k" to sort by the key, the extension)
					for extension in extensions:
						html += '<option value="' + extension[0]
						if extension[0] in sharedUsers[sharedUser]:
							html += '" selected="selected">'
						else:
							html += '">'
						html += extension[0] + ": " + extension[1] + "</option>"
					html += """
								</select><br />
								<button type="submit" class="btn btn-primary" style="margin:5px;">Update</button>
								<a href="/?deleteUser=""" + sharedUser + """" class="btn btn-danger" style="margin:5px;" role="button">Delete User</a>
								</div>
								</form>
								</div>
							</div>"""
				# Options Panel to enable/disable logging, add shared users and save/load config. Buttons loaded dynamically.
				html += """<div class="panel panel-default" style="height:450px;float:left;width:250px;overflow:hidden;margin:5px;">
							<div class="panel-heading">Options<br/>&nbsp;</div>
							<div class="panel-body" style="text-align:center">"""
				if loggingEnabled:
					html += '<a href="/?loggingEnabled=disable" class="btn btn-danger" style="margin:5px;" role="button">Disable logging</a>'
				else:
					html += '<a href="/?loggingEnabled=enable" class="btn btn-success" style="margin:5px;" role="button">Enable logging</a>'
				html += '<hr/>'
				if unansweredEnabled:
					html += '<a href="/?unanswered=disable" class="btn btn-danger" style="margin:5px;" role="button">Disable logging of<br/>unanswered calls</a>'
				else:
					html += '<a href="/?unanswered=enable" class="btn btn-success" style="margin:5px;" role="button">Enable logging of<br/>unanswered calls</a>'
				if voicemailEnabled:
					html += '<a href="/?voicemail=disable" class="btn btn-danger" style="margin:5px;" role="button">Disable logging of<br/>voicemail</a>'
				else:
					html += '<a href="/?voicemail=enable" class="btn btn-success" style="margin:5px;" role="button">Enable logging of<br/>voicemail</a>'
				html += """<hr/><form role="form" action="/" method="GET" >
							<div class="form-group">
							<select class="form-control" name="addUser">"""
				usersForShared = sorted(activeUsers.iteritems(), key=lambda (k,v): v['Username']) # Sort users by Username
				for user in usersForShared:
					html += '<option value ="' + user[0] + '">' + user[1]['Username'] + "</option>"
				html += """
							</select>
							<button type="submit" class="btn btn-success" style="margin:5px;">Add Shared User</button>
							</div>
							</form>
					</div></div>

					<div class="panel panel-default" style="height:450px;float:left;width:250px;overflow:hidden;margin:5px;">
						<div class="panel-heading">Load/Save Config<br/>&nbsp;</div>
						<div class="panel-body" style="text-align:center">
						<form class="form" role=" action="/" method="GET" >
						  <div class="form-group">
						      <input type="text" class="form-control" name="savename" placeholder="Name">
						  </div>
						  <div class="form-group">
						      <input type="password" class="form-control" name="savesecret" placeholder="Passphrase">
						  </div>
						  <div class="form-group">
						  	<button type="submit" class="btn btn-warning" style="margin:5px;">Save</button>
						  </div>
						</form>
						<hr/><form role="form" action="/" method="GET" >
							<div class="form-group">
							<select class="form-control" name="loadname">"""
				for name in getSavedConfigs():
					html += '<option value ="' + name + '">' + name + "</option>"
				html += """
							</select>
							</div>
							<div class="form-group">
								<input type="password" class="form-control" name="loadsecret" placeholder="Passphrase">
							<div class="form-group">
							<button type="submit" class="btn btn-warning" style="margin:5px;">Load</button>
							</div></div>
							</form>
					</div>
					</body>
				</html>
				"""
				self.wfile.write(bytes(html))
		
		logging.info("Time taken for request: " + str(time.time() - starttime))

	def log_request(self, code=None, size=None):
		"""
		Prints out when request made
		"""
		logging.info("Request")

	def log_message(self, format, *args):
		"""
		Prints out when message transmitted
		"""
		logging.info("Message")

def sliceDict(d, s):
	"""
	Return dictionary d only with keys starting with s
	"""
	return {k:v for k,v in d.iteritems() if k.startswith(s)}

def saveData(data, filename, passphrases):
	"""
	Save data in filename using pickle. Give data as tuple like (obj0, obj1, ...).
	"""
	encoder = encryptedpickle.EncryptedPickle(signature_passphrases=passphrases, encryption_passphrases=passphrases)

	datafile = open(os.path.join(os.path.join(os.path.dirname(__file__)), str(filename)), 'wb')
	pickle.dump(encoder.seal(data), datafile)

def loadData(filename, passphrase):
	"""
	Load previously saved data. Returns data as saved; usually tuple like (obj0, obj1, ...).
	"""
	passphrases = {0: passphrase}
	encoder = encryptedpickle.EncryptedPickle(signature_passphrases=passphrases, encryption_passphrases=passphrases)

	fname = os.path.join(os.path.join(os.path.dirname(__file__)), str(filename))
	if os.path.isfile(fname):
		datafile = open(fname, 'rb')
		try:
			data = encoder.unseal(pickle.load(datafile))
			return data
		except:
			return None
	else:
		return None

def getAllExtensions():
	'''
	Returns all extensions registered in FreePBX as a dictionary in the format {'ext': 'Name'}
	'''
	# Initialise Telnet connection and log in.
	tn_ami = telnetlib.Telnet(ASTERISK_HOST, ASTERISK_PORT)
	tn_ami.read_until("Asterisk Call Manager/1.1")
	tn_ami.write("Action: Login\nUsername: " + ASTERISK_CMD_USER + "\nSecret: " + ASTERISK_CMD_SECRET + "\n\n")

	# Wait for fully booted
	tn_ami.read_until("Status: Fully Booted")

	# Query for cidname from DB (FreePBX style)
	tn_ami.write("Action: Command\nCommand: database showkey cidname\n\n")
	data = tn_ami.read_until("--END COMMAND--")
	
	extensions = {}

	# Analyse data to find last name
	if len(data) > 0:
		lines = data.split("\n")
		for line in lines:
			match = re.search('/AMPUSER/\d{4}.+', line)
			if match:
				cidline = match.group(0)
				extension = re.search('\d+', cidline).group(0)
				words = re.findall('\w+', cidline)
				fullname = " ".join(words[3:len(words)]) # all words after the second (i.e. everything belonging to the extensions)
				extensions[extension] = fullname

	# Close Telnet connection
	tn_ami.write("Action: Logoff" + "\n\n")
	tn_ami.close()

	return extensions

def getActiveUsers():
	'''
	Returns list of all active SalesForce Users
	'''
	activeUsers = {}
	query = "SELECT Name, Id, Username FROM User WHERE IsActive = true"
	result = sf.query_all(query)["records"]
	lastAPIconnection = time.time()
	for user in result:
		activeUsers[user['Id']] = {}
		activeUsers[user['Id']]['Name'] = user['Name']
		activeUsers[user['Id']]['Username'] = user['Username']
	return activeUsers

def getUsersNames(users):
	'''
	Returns list of all active SalesForce Users
	'''
	usersNames = []
	for user in users:
		usersNames.append(users[user]['Name'])
	return usersNames

def getUserId(fullName):
	'''
	Returns the salesforce ID of the user with the matching name.
	'''
	query = "SELECT Id FROM User WHERE Name LIKE '" + fullName + "'"
	result = sf.query_all(query)["records"]
	lastAPIconnection = time.time()
	if len(result) == 1:
		return result[0]['Id'] # return Id of first result
	else:
		return None

def getSavedConfigs():
	filenames = set()
	for file in os.listdir(os.path.dirname(__file__)):
		if file.endswith(".epk"):
			filenames.add(file[:-4])
	return filenames

def getNumberTerm(phonenumber):
	'''
	Returns wildcarded version of phonenumber.
	Strips +/00 off of the beginning, and the next two digits to account for country codes
	'''
	# Strip + or 00 or 0 off of phone number
	number = phonenumber.strip('+')
	number = number.strip('00') 
	# Strip first 2 digits of phone number in case the CID (caller provider specific) includes a country code
	number = number[2:len(number)]
	term = '%' # searchterm for salesfore SQOL
	for digit in number:
		term += (digit + "%")
	return term

def getNumberOfContacts(phonenumber):
	'''
	Returns the number of salesforce contacts associated with the phone number
	'''
	term = getNumberTerm(phonenumber)

	results = sf.query_all("SELECT AccountId FROM Contact WHERE Phone LIKE '" + term + "' OR MobilePhone LIKE '" + term + "'")["records"]
	lastAPIconnection = time.time()
	return len(results)

def getNumberOfAccounts(phonenumber):
	'''
	Returns the number of salesforce contacts associated with the phone number
	'''
	term = getNumberTerm(phonenumber)

	results = sf.query_all("SELECT Id FROM Account WHERE Phone LIKE '" + term + "'")["records"]
	lastAPIconnection = time.time()
	if (len(results) > 0):
		return len(results)
	else: # search contacts for phone numbers and count associated accounts
		# Create empty set for couting unique accounts with that number
		uniqueAccounts = set()
		
		# Search contacts for phones
		results = sf.query_all("SELECT AccountId FROM Contact WHERE Phone LIKE '" + term + "' OR MobilePhone LIKE '" + term + "'")["records"]
		lastAPIconnection = time.time()
		for contact in results:
			uniqueAccounts.add(contact['AccountId'])

		return len(uniqueAccounts)

def getAccountId(phonenumber):
	'''
	Returns the Account ID of the salesforce account associated with the phone number
	'''
	term = getNumberTerm(phonenumber)
	#Query database for accounts
	results = sf.query_all("SELECT Id FROM Account WHERE Phone LIKE '" + term + "'")["records"]
	lastAPIconnection = time.time()
	if (len(results) == 1): # return ID of only match
		return results[0]['Id']
	else:
		# No Account found, looking for contacts
		results = sf.query_all("SELECT AccountId FROM Contact WHERE Phone LIKE '" + term + "'")["records"]
		lastAPIconnection = time.time()
		if (len(results) == 1): # return ID of only match
			return results[0]['AccountId']
		else:
			# No Contact found; looking for mobiles
			results = sf.query_all("SELECT AccountId FROM Contact WHERE MobilePhone LIKE '" + term + "'")["records"]
			lastAPIconnection = time.time()
			if (len(results) == 1): # return ID of only match
				return results[0]['AccountId']
	return None

def getContactId(phonenumber):
	'''
	Returns the Contact ID of the salesforce contact associated with the phone number
	'''
	term = getNumberTerm(phonenumber)
	#Query database for accounts
	results = sf.query_all("SELECT Id FROM Contact WHERE Phone LIKE '" + term + "' OR MobilePhone LIKE '" + term + "'")["records"]
	lastAPIconnection = time.time()
	if (len(results) == 1): # return ID of only match
		return results[0]['Id']
	return None

def createTask(accountId, summary, userId, subject='Call', contactId=None):
	'''
	Creates new, completed "Call" task in SalesForce to show up in the account's Activity History
	'''
	if loggingEnabled:
		sf.Task.create({
			'Type':'Called',
			'WhatId':accountId,
			'OwnerID':userId,
			'Subject':subject,
			'Status':'Completed',
			'WhoId':contactId,
			'Description':'A call has been logged automagically.',
			'Status':'Completed',
			'Priority':'Normal',
			'Summary__c':summary,
			'ActivityDate':time.strftime('%Y-%m-%d')
			})
		lastAPIconnection = time.time()
		logging.info("\tLogged.")
	else:
		logging.info("\t------")
		logging.info("\tLOGGING NOT ENABLED")
		logging.info("\t------")

def getEventFieldValue(field, event):
	'''
	Returns value of field from cdr event as reported by the AMI.
	Event must be in the telnet format as string like "field: value\\r\\nfield:value\\r\\n"
	'''
	pattern = field + ": .+"
	match = re.search(pattern, event)
	if match:
		line = match.group(0).split(" ")
		return ' '.join(line[1:len(line)]).strip("\r")
	else:
		return None

def getQueueMembers(extension):
	'''
	Returns list of extensions on given queue in FreePBX.
	'''
	members = []
	# Initialise Telnet connection and log in.
	tn_ami = telnetlib.Telnet(ASTERISK_HOST, ASTERISK_PORT)
	tn_ami.read_until("Asterisk Call Manager/1.1")
	tn_ami.write("Action: Login\nUsername: " + ASTERISK_CMD_USER + "\nSecret: " + ASTERISK_CMD_SECRET + "\n\n")

	# Wait for fully booted
	tn_ami.read_until("Status: Fully Booted")

	# Query for queue info in Asterisk
	tn_ami.write("Action: Command\nCommand: queue show " + extension + "\n\n")
	data = tn_ami.read_until("--END COMMAND--")
	
	# Analyse data to find last name
	if len(data) > 0:
		lines = data.split("\n")
		for line in lines:
			match = re.search('\(Local/\d{4}', line) # Assuming queue entries, and queue entries only, are like '*(Local/1339*'
			if match:
				members.append(match.group(0)[-4:])

	# Close Telnet connection
	tn_ami.write("Action: Logoff" + "\n\n")
	tn_ami.close()

	if len(members) > 0:
		return members
	else:
		return None

def getSharedUser(extension):
	'''
	Returns userId if extension is saved in config as a shared account.
	This needs to be done manually!
	'''
	for i in sharedUsers:
		if extension in sharedUsers[i]:
			return i
	return None

def makeSummary(event):
	"""
	Returns string detailing duration and disposition of CDR event in 'event'.
	"""
	if getEventFieldValue('Disposition', event) == "NO ANSWER":
		return "No Answer"
	if getEventFieldValue('LastApplication', event) == "VoiceMail":
		return "Voicemail: " + str(datetime.timedelta(seconds=int(getEventFieldValue('BillableSeconds', event))))
	return "Duration: " + str(datetime.timedelta(seconds=int(getEventFieldValue('BillableSeconds', event))))

def isLoggingEnabled(extension):
	"""
	Checks if logging is enabled for this extension.
	"""
	if extension in whitelistLogging:
		return True
	else:
		return False

def mainloop():
	'''
	Main Function: Establishes connection to AMI and reads CDR events.
	Every 5 seconds, it checks if an event has been detected, and if so it checks whether
		- the call was inbound or outbound
		- the user is on a shared SalesForce account, and if not
			- the user's extension is whitelisted (marked 'active' in the webinterface)
		- the phone number is registered with SalesForce (account or contact)
	If these tests validate, it logs the call in SalesForce as Activity (or 'Task') with relevant information, such as the duration and disposition, if configured.
	'''
	global lastAPIconnection
	# Initialise Telnet connection and log in.
	tn_cdr = telnetlib.Telnet(ASTERISK_HOST, ASTERISK_PORT)
	tn_cdr.read_until("Asterisk Call Manager/1.1")
	tn_cdr.write("Action: Login\nUsername: " + ASTERISK_CDR_USER + "\nSecret: " + ASTERISK_CDR_SECRET + "\n\n")

	#Wait for fully booted
	tn_cdr.read_until("Status: Fully Booted")
	logging.info("AMI connection established, starting loop")
	# Infinite loop for continuous AMI communication
	while True:
		data = tn_cdr.read_very_eager()
		if len(data) > 0:
			events = data.split("\r\n\r\n")
			for event in events:
				if str(getEventFieldValue('Event', event)) == 'Cdr':
					logging.info("CDR logged:")
					# Inbound calls to Extension
					if str(getEventFieldValue('DestinationContext', event)) == 'from-did-direct':
						logging.info("\tInbound")
						if isLoggingEnabled(getEventFieldValue('Destination', event)):
							# check whether the call has NOT been answered and if so, whether logging of unsanwered calls is enabled
							if not (getEventFieldValue('Disposition', event) == "NO ANSWER" and not unansweredEnabled):
								if not (getEventFieldValue('LastApplication', event) == "VoiceMail" and not voicemailEnabled):

									# Check if extension is saved as shared User in config
									salesforceUser = getSharedUser(getEventFieldValue('Destination', event))
									# If not saved, check if extension matches any SalesForce user
									if not salesforceUser:
										localName = getAllExtensions()[getEventFieldValue('Destination', event)]
										if localName:
											salesforceUser = getUserId(str(localName))
									# If SalesForce user matched via either of the above, proceed recordings.
									if salesforceUser:
										# check for number of contacts with SRC number and take action based on that:
										#	0 or 2+: Search how many accounts (inc. associated contacts) are associated with the number
										#		0: no match -> no log
										#		1: exact match -> log with account
										#		2: no exact match -> don't log
										#	1: Log call with that contact
										numberOfContacts = getNumberOfContacts(getEventFieldValue('Source', event))

										if (numberOfContacts != 1): # 0 or 2+ contacts associated with phone number
											numberOfAccounts = getNumberOfAccounts(getEventFieldValue('Source', event))
											if (numberOfAccounts == 0):
												logging.info("\tNo associated SalesForce account found.")
											elif(numberOfAccounts == 1):
												salesforceAccount = getAccountId(getEventFieldValue('Source', event))
												logging.info("\tSRC: " + getEventFieldValue('Source', event))
												logging.info("\tSFA: " + salesforceAccount)
												logging.info("\tDST: " + getEventFieldValue('Destination', event))
												logging.info("\tSFU: " + salesforceUser)
												logging.info("\tSEC: " + getEventFieldValue('BillableSeconds', event))
												logging.info("\tLogging Call in SalesForce...")
												createTask(salesforceAccount, makeSummary(event), salesforceUser, "Call Inbound; Contact unknown", None)
												logging.info("\tLogged.")
											elif(numberOfAccounts > 1):
												logging.info("\t" + str(numberOfAccounts) + " accounts found. No exact match possible.")
										else: # exact contact salesforceAccountc
											salesforceAccount = getAccountId(getEventFieldValue('Source', event))
											salesforceContact = getContactId(getEventFieldValue('Source', event))
											logging.info("\tSRC: " + getEventFieldValue('Source', event))
											logging.info("\tSFA: " + salesforceAccount)
											logging.info("\tSFC: " + salesforceContact)
											logging.info("\tDST: " + getEventFieldValue('Destination', event))
											logging.info("\tSFU: " + salesforceUser)
											logging.info("\tSEC: " + getEventFieldValue('BillableSeconds', event))
											logging.info("\tLogging Call in SalesForce...")
											createTask(salesforceAccount, makeSummary(event), salesforceUser, "Call Inbound", salesforceContact)

									else:
										logging.info("\tNo associated SalesForce user found.")
								else:
									logging.info("\tCalls to voicemail not logged.")
							else:
								logging.info("\tUnanswered calls not logged.")
						else:
							logging.info("\tLogging not enabled for this extension.")

					# Call From Internal
					elif str(getEventFieldValue('DestinationContext', event)) == 'from-internal':
						logging.info("\tFrom Internal")
						if isLoggingEnabled(getEventFieldValue('Source', event)):
							# check whether the call has NOT been answered and if so, whether the extension has logging of unsanwered calls enabled
							if not (getEventFieldValue('Disposition', event) == "NO ANSWER" and not unansweredEnabled):
								if (len(str(getEventFieldValue('Destination', event))) > 4):
									# Check if extension is saved as shared User in config
									salesforceUser = getSharedUser(getEventFieldValue('Source', event))
									# If not saved, check if extension matches any SalesForce user
									if not salesforceUser:
										localName = getAllExtensions()[getEventFieldValue('Source', event)]
										if localName:
											salesforceUser = getUserId(str(localName))
									# If SalesForce user matched via either of the above, proceed recordings.
									if salesforceUser:
										# check for number of contacts with DST number and take action based on that:
										#	0 or 2+: Search how many accounts (inc. associated contacts) are associated with the number
										#		0: no match -> no log
										#		1: exact match -> log with account
										#		2: no exact match -> don't log
										#	1: Log call with that contact
										numberOfContacts = getNumberOfContacts(getEventFieldValue('Destination', event))
										if (numberOfContacts != 1): # 0 or 2+ contacts associated with phone number
											numberOfAccounts = getNumberOfAccounts(getEventFieldValue('Destination', event))
											if (numberOfAccounts == 0):
												logging.info("\tNo associated SalesForce account found.")
											elif(numberOfAccounts == 1):
												salesforceAccount = getAccountId(getEventFieldValue('Destination', event))
												logging.info("\tSRC: " + getEventFieldValue('Source', event))
												logging.info("\tSFA: " + salesforceAccount)
												logging.info("\tDST: " + getEventFieldValue('Destination', event))
												logging.info("\tSFU: " + salesforceUser)
												logging.info("\tSEC: " + getEventFieldValue('BillableSeconds', event))
												logging.info("\tLogging Call in SalesForce...")
												createTask(salesforceAccount, makeSummary(event), salesforceUser, "Call Outbound; Contact unknown", None)
												logging.info("\tLogged.")
											elif(numberOfAccounts > 1):
												logging.info("\t" + str(numberOfAccounts) + " accounts found. No exact match possible.")
										else: # exact contact match
											salesforceAccount = getAccountId(getEventFieldValue('Destination', event))
											salesforceContact = getContactId(getEventFieldValue('Destination', event))
											logging.info("\tSRC: " + getEventFieldValue('Source', event))
											logging.info("\tSFA: " + salesforceAccount)
											logging.info("\tSFC: " + salesforceContact)
											logging.info("\tDST: " + getEventFieldValue('Destination', event))
											logging.info("\tSFU: " + salesforceUser)
											logging.info("\tSEC: " + getEventFieldValue('BillableSeconds', event))
											logging.info("\tLogging Call in SalesForce...")
											createTask(salesforceAccount, makeSummary(event), salesforceUser, "Call Outbound", salesforceContact)

									else:
										logging.info("\tNo associated SalesForce user found.")
								else:
									logging.info("\tExtension dialled.")
							else:
								logging.info("\tUnanswered calls not logged.")
						else:
							logging.info("\tLogging not enabled for this extension.")
					else:
						logging.info("\t" + str(getEventFieldValue('DestinationContext', event)))

		# if last API call to SF older than 9 minutes make new API call to avoid session timeout
		if ((time.time()-(lastAPIconnection)) > (60*9)):
			logging.info("Making dummy API call to avoid SF session timeout...")
			sf.User.deleted(datetime.datetime.now(pytz.UTC) - datetime.timedelta(days=2), datetime.datetime.now(pytz.UTC))
			lastAPIconnection = time.time()
			logging.info("API call made.")
		
		time.sleep(5)

### START PROGRAM ###

lastAPIconnection = time.time()


if __name__ == "__main__":
	global sharedUsers
	global whitelistLogging
	global unansweredEnabled
	global loggingEnabled
	global voicemailEnabled
	global port
	global configfile
	global filesecret
	global authKey
	global showMessage
	
	try:
		authKey = base64.b64encode(USERNAME + ":" + PASSWORD)
	except:
		logging.warning("Not authentication for HTTP set.")


	try:
		opts, args = getopt.getopt(sys.argv[1:],"hp:f:s:",["help","port=","configfile=","secret="])
	except getopt.GetoptError:
		print "test.py -p <port> -f <configfile> -s <secret>"
		sys.exit(2)
	for opt, arg in opts:
		if (opt == '-h' or opt == '--help'):
			print "test.py -p <port> -f <configfile> -s <secret>"
			sys.exit()
		elif opt in ("-p", "--port"):
			port = arg
		elif opt in ("-f", "--configfile"):
			configfile = arg
		elif opt in ("-s", "--secret"):
			filesecret = arg
	
	exitnow = False
	try:
		configfile
		try:
			filesecret
		except:
			print "Please specify secret if you would like to use a pre-saved config.\ntest.py -p <port> -f <configfile> -s <secret>"
			exitnow = True
	except:
		pass

	if exitnow:
		sys.exit(2)

	try:
		port = int(port)
	except:
		port = 8008

	try:
		logging.info("Trying to load config from " + configfile)

		data = loadData(configfile, filesecret*4)
		sharedUsers = data[0]
		whitelistLogging = data[1]
		unansweredEnabled = data[2]
		loggingEnabled = data[3]
		voicemailEnabled = data[4]
		authKey = data[5]

		dataLoaded = True
	except: # reset all
			logging.warning("Could not load data from configfile")
			dataLoaded = False
	
	if not dataLoaded:
			sharedUsers = {}
			whitelistLogging = ()
			unansweredEnabled = True
			loggingEnabled = False
			voicemailEnabled = True

	# create logged in Salesforce Object
	sf = Salesforce(instance=SF_INSTANCE, username=SF_USERNAME, password=SF_PASSWORD, security_token=SF_TOKEN)

	showMessage = set()

	# Create new threads
	serverThread = server()

	# Start new Threads
	serverThread.start()
	mainloop()
else:
	print "Please start program directly to have it work correctly."