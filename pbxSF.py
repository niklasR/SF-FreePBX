#! /usr/bin/env python
import sys
import getopt
import telnetlib
import re
import time
import datetime
import pytz
import threading
import pickle
import os
import base64
import logging
import smtplib
import getpass

from flask import Flask, render_template, request, redirect
from multiprocessing import Process
from simple_salesforce import Salesforce
from encryptedpickle import encryptedpickle
from email.mime.text import MIMEText
from email.MIMEMultipart import MIMEMultipart

logging.basicConfig(format='%(asctime)s %(message)s', level=logging.DEBUG)

if __name__ != "__main__":
	sys.exit("Not main. Exiting..")

class CommunicatorThread(threading.Thread):

	def run(self):
		'''
		Main Function: Establishes connection to AMI and reads CDR events.
		Every 5 seconds, it checks if an event has been detected, and if so it checks whether
			- the call was inbound or outbound
			- the user is on a shared SalesForce account, and if not
				- the user's extension is whitelisted (marked 'active' in the webinterface)
			- the phone number is registered with SalesForce (account or contact)
		If these tests validate, it logs the call in SalesForce as Activity (or 'Task') with relevant information, such as the duration and disposition, if configured.
		'''
		global astValid
		global sfValid
		global asteriskAuth
		global voicemailUsers
		global unansweredUsers
		global lastAPIconnection
		global breakCommunicatorThread
		while not breakCommunicatorThread:
			if (astValid and sfValid):
				logging.info("Connecting to Asterisk..")
				global lastAPIconnection
				# Initialise Telnet connection and log in.
				tn_cdr = telnetlib.Telnet(asteriskAuth[0], asteriskAuth[1])
				tn_cdr.read_until("Asterisk Call Manager/" + asteriskAuth[6])
				tn_cdr.write("Action: Login\nUsername: " + asteriskAuth[4] + "\nSecret: " + asteriskAuth[5] + "\n\n")

				#Wait for fully booted
				tn_cdr.read_until("Status: Fully Booted")
				logging.info("AMI connection established, starting loop")
				# Infinite loop for continuous AMI communication
				while not breakCommunicatorThread:
					global asteriskUpdated
					if asteriskUpdated:
						asteriskUpdated = False
						break
					if (astValid and sfValid):
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
											# Check if extension is saved as shared User in config
											salesforceUser = getSharedUser(getEventFieldValue('Destination', event))
											# If not saved, check if extension matches any SalesForce user
											if not salesforceUser:
												localName = getAllExtensions()[getEventFieldValue('Destination', event)]
												if localName:
													salesforceUser = getUserId(str(localName))
											# If SalesForce user matched via either of the above, proceed recordings.
											if salesforceUser:
												if not (getEventFieldValue('LastApplication', event) == "VoiceMail" and not voicemailUsers[salesforceUser]):
													# check whether the call has NOT been answered and if so, whether logging of unsanwered calls is enabled
													if not (getEventFieldValue('Disposition', event) == "NO ANSWER" and not unansweredUsers[salesforceUser]):
														# check for number of contacts with SRC number and take action based on that:
														#	0 or 2+: Search how many accounts (inc. associated contacts) are associated with the number
														#		0: no match -> no log
														#		1: exact match -> log with account
														#		2: no exact match -> don't log
														#	1: Log call with that contact
														try:
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
														except Exception as detail:
															logging.warning("Event error:", detail)
													else:
														logging.info("\tUnanswered calls not logged.")
												else:
													logging.info("\tCalls to voicemail not logged.")
											else:
												logging.info("\tNo associated SalesForce user found.")
										else:
											logging.info("\tLogging not enabled for this extension.")

									# Call From Internal
									elif str(getEventFieldValue('DestinationContext', event)) == 'from-internal':
										logging.info("\tFrom Internal")
										if isLoggingEnabled(getEventFieldValue('Source', event)):
											# check whether the call has NOT been answered and if so, whether the extension has logging of unsanwered calls enabled
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
													# check whether the call has NOT been answered and if so, whether logging of unsanwered calls is enabled
													if not (getEventFieldValue('Disposition', event) == "NO ANSWER" and not unansweredUsers[salesforceUser]):
														# check for number of contacts with DST number and take action based on that:
														#	0 or 2+: Search how many accounts (inc. associated contacts) are associated with the number
														#		0: no match -> no log
														#		1: exact match -> log with account
														#		2: no exact match -> don't log
														#	1: Log call with that contact
														try:
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
														except Exception as detail:
															logging.warning("Event error:", detail)
													else:
														logging.info("\tUnanswered calls not logged.")
												else:
													logging.info("\tNo associated SalesForce user found.")
											else:
												logging.info("\tExtension dialled.")
										else:
											logging.info("\tLogging not enabled for this extension.")
									else:
										logging.info("\t" + str(getEventFieldValue('DestinationContext', event)))
						# if last API call to SF older than 9 minutes make new API call to avoid session timeout
						if ((time.time()-(lastAPIconnection)) > (60*9)) and (sf != None):
							logging.info("Making dummy API call to avoid SF session timeout...")
							sf.User.deleted(datetime.datetime.now(pytz.UTC) - datetime.timedelta(days=2), datetime.datetime.now(pytz.UTC))
							lastAPIconnection = time.time()
							logging.info("API call made.")
						time.sleep(5)
					else:
						break

def loadData(filename, passphrase):
	"""
	Load previously saved data. Returns data as saved; usually tuple like (obj0, obj1, ...).
	"""
	passphrases = {0: passphrase}
	encoder = encryptedpickle.EncryptedPickle(signature_passphrases=passphrases, encryption_passphrases=passphrases)

	fname = os.path.join(os.path.join(os.path.dirname(os.path.abspath(__file__))), str(filename))
	if os.path.isfile(fname):
		datafile = open(fname, 'rb')
		try:
			data = encoder.unseal(pickle.load(datafile))
			return data
		except:
			return None
	else:
		return None

def updateSF(salesforceAuth):
	global sfValid
	global sf
	try:
		sf = Salesforce(instance=salesforceAuth[0], username=salesforceAuth[1], password=salesforceAuth[2], security_token=salesforceAuth[3])
		sfValid = True
		logging.info("SF Object created.")
		return True
	except:
		sfValid = False
		logging.warning("SF Object could not be created.")
		return False

def create_app():
	app = Flask(__name__)

	def initialiseProgram():
		global sharedUsers
		global whitelistLogging
		global loggingEnabled
		global voicemailEnabled
		global port
		global configfile
		global filesecret
		global showMessage
		global sfValid
		global salesforceAuth
		global asteriskAuth
		global astValid
		global smtpAuth
		global smtpValid
		global emailEnabled
		global lastAPIconnection
		global asteriskUpdated
		global emailUsers
		global voicemailUsers
		global unansweredUsers
		global sf
		global breakCommunicatorThread

		with dataLock:
			# Do your stuff with commonDataStruct Here
			asteriskUpdated = False
			sf = None

			try:
				opts, args = getopt.getopt(sys.argv[1:],"hp:f:s:",["help","port=","configfile=","secret="])
			except getopt.GetoptError:
				print "test.py -p <port> -f <configfile>"
				sys.exit(2)
			for opt, arg in opts:
				if (opt == '-h' or opt == '--help'):
					print "test.py -p <port> -f <configfile>"
					sys.exit()
				elif opt in ("-p", "--port"):
					port = arg
				elif opt in ("-f", "--configfile"):
					configfile = arg
					filesecret = getpass.getpass("Enter password for " + arg + ": ")

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
				port = 8000
		try:
			logging.info("Trying to load config from " + configfile)

			data = loadData(configfile, filesecret*4)
			sharedUsers = data[0]
			whitelistLogging = data[1]
			loggingEnabled = data[2]
			salesforceAuth = data[3]
			asteriskAuth = data[4]
			astValid = data[5]
			sfValid = data[6]
			smtpAuth = data[7]
			smtpValid = data[8]
			emailEnabled = data[9]
			emailUsers = data[10]
			voicemailUsers = data[11]
			unansweredUsers = data[12]

			updateSF(salesforceAuth)

			dataLoaded = True
		except: # reset all
			logging.info("Could not load data from configfile")
			dataLoaded = False

		if not dataLoaded:
			logging.info("Loading default data")
			sharedUsers = {}
			whitelistLogging = tuple()
			loggingEnabled = False
			salesforceAuth = ('', '', '', '')
			smtpAuth = ('', '', '', '')
			asteriskAuth = ('', '', '', '', '', '', '')
			sfValid = False
			smtpValid = False
			astValid = False
			emailEnabled = False
			emailUsers = {}
			voicemailUsers = {}
			unansweredUsers = {}
		
		showMessage = set()

		lastAPIconnection = 0.0
		breakCommunicatorThread = False

	# Initiate
	initialiseProgram()
	return app

dataLock = threading.Lock()
app = create_app()

@app.route('/', methods=['GET', 'POST'])	 
def serveWebRequest():
	# Load global names
	global salesforceAuth
	global whitelistLogging
	global emailEnabled
	global sharedUsers
	global loggingEnabled
	global showMessage
	global sfValid
	global sf
	global asteriskAuth
	global astValid
	global asteriskUpdated
	global smtpValid
	global smtpAuth
	global emailUsers
	global voicemailUsers
	global unansweredUsers

	# Time request
	starttime = time.time()
	
	if request.method == 'GET':
		items = request.args
		qs = {}
		for item in items:
			qs[item] = items.getlist(item)

		# Print GET content
		dict_print = ""
		for key, value in qs.items():
			dict_print += "{} : {}".format(key, value) # for debug/log
			dict_print += " | "
		logging.info("GET arguments: " + dict_print)

		# Enable/Disable sending emails
		if 'emailEnabled' in qs:
			if qs['emailEnabled'][0] == 'disable':
				emailEnabled = False
			elif qs['emailEnabled'][0] == 'enable':
				emailEnabled = True

		# Enable/Disable logging
		if 'loggingEnabled' in qs:
			if qs['loggingEnabled'][0] == 'disable':
				loggingEnabled = False
			elif qs['loggingEnabled'][0] == 'enable':
				loggingEnabled = True

		# Clear lists
		if 'clear' in qs:
			if qs['clear'][0] == 'active':
				whitelistLogging = tuple()
				emailUsersTemp = {} # new emailUsers
				for userId in emailUsers:
					if userId in sharedUsers:
						emailUsersTemp[userId] = emailUsers[userId]
				emailUsers = emailUsersTemp

			elif qs['clear'][0] == 'email':
				for userId in emailUsers:
					emailUsers[userId] = False

			elif qs['clear'][0] == 'voicemail':
				for userId in voicemailUsers:
					voicemailUsers[userId] = False

			elif qs['clear'][0] == 'unanswered':
				for userId in unansweredUsers:
					unansweredUsers[userId] = False

		# Delete Shared User
		if 'deleteUser' in qs:
			logging.info("Deleting shared User")
			for userId in qs['deleteUser']:
				if userId in sharedUsers:
					del sharedUsers[userId]
					showMessage.add("Shared User deleted.")
				else:
					logging.warning("UserId not found in sharedUsers.")
				if userId in emailUsers:
					del emailUsers[userId]
				else:
					logging.warning("UserId not found in emailUsers.")
				if userId in voicemailUsers:
					del voicemailUsers[userId]
				else:
					logging.warning("UserId not found in voicemailUsers.")
				if userId in unansweredUsers:
					del unansweredUsers[userId]
				else:
					logging.warning("UserId not found in unansweredUsers.")

		 # if any GET arguments, redirect to clean / after processing to avoid double requests if user refreshes
		if len(qs) > 0:
			return redirect('/')

	if request.method == 'POST':
		"""Respond to a POST request."""

		# Time request
		starttime = time.time()
		
		items = request.form
		qs = {}
		for item in items:
			qs[item] = items.getlist(item)

		# Print POST content
		dict_print = ""
		for key, value in qs.items():
			dict_print += "{} : {}".format(key, value) # for debug/log
			dict_print += " | "
		logging.info("POST: " + dict_print)

		# Update active extensions
		if 'whitelist' in qs:

			logging.debug("Deleting users from mailing list...")
			logging.debug("Old mailing list: " + str(emailUsers))
			logging.debug("Old whitelist: " + str(whitelistLogging))


			activeUsers = getActiveUsers()
			allExtensions = getAllExtensions()

			userIds = {}
			for user in activeUsers:
				userIds[activeUsers[user]['Name']] = user

			# add new extensions to email list
			whitelistUsers = set() # set for user IDs of all whitelisted extensions
			# populate whitelistUsers
			for extension in qs['whitelist']:
				whitelistUsers.add(userIds[str(allExtensions[extension])])
			# add Ids
			for userId in whitelistUsers:
				if userId not in emailUsers:
					emailUsers[userId] = True
				if userId not in voicemailUsers:
					voicemailUsers[userId] = True
				if userId not in unansweredUsers:
					unansweredUsers[userId] = True

			# Remove old IDs
			removedExts = set(whitelistLogging) - set(qs['whitelist'])
			removedUsers = set()
			for extension in removedExts:
				removedUsers.add(userIds[str(allExtensions[extension])])
			# remove Ids
			for userId in removedUsers:
				del emailUsers[userId]
				del voicemailUsers[userId]
				del unansweredUsers[userId]
			logging.debug("New mailing list: " + str(emailUsers))

			# Update general logging list
			whitelistLogging = tuple(qs['whitelist']) # Tuple, because sets not JSON serialisable by default
			logging.debug("New whitelist: " + str(whitelistLogging))

		# Save config (encrypted)
		if ('savename' in qs) and ('savesecret' in qs):
			if len(qs['savesecret'][0]) >= 8:
				saveData((sharedUsers, whitelistLogging, loggingEnabled, salesforceAuth, asteriskAuth, astValid, sfValid, smtpAuth, smtpValid, emailEnabled, emailUsers, voicemailUsers, unansweredUsers), qs['savename'][0] + ".epk", {0: qs['savesecret'][0]*4})
				logging.info("Config saved as " + qs['savename'][0] + ".epk")
				showMessage.add("Config saved as '" + qs['savename'][0] + "'.")
			else:
				showMessage.add("Passphrase too short - needs to be at least 8 characters")
				logging.warning("Passphrase too short - needs to be at least 8 characters")

		# Load config (encrypted)
		if ('loadname' in qs) and ('loadsecret' in qs):
			data = loadData(qs['loadname'][0] + ".epk", qs['loadsecret'][0]*4)
			if data:
				if len(data) == 13:
					sharedUsers = data[0]
					whitelistLogging = data[1]
					loggingEnabled = data[2]
					salesforceAuth = data[3]
					asteriskAuth = data[4]
					astValid = data[5]
					sfValid = data[6]
					smtpAuth = data[7]
					smtpValid = data[8]
					emailEnabled = data[9]
					emailUsers = data[10]
					voicemailUsers = data[11]
					unansweredUsers = data[12]

					updateSF(salesforceAuth)
					showMessage.add("Config loaded succesfully.")
					logging.info("Config loaded from file: " + qs['loadname'][0])
				else:
					showMessage.add("Config could not be loaded: Format incompatible.")
			else:
				showMessage.add("Config could not be loaded: File not found or passphrase wrong.")
		elif ('loadname' in qs):
			showMessage.add("Please enter passphrase.")

		# Update Asterisk Data
		if 'asterisk_cdr_secret' in qs and 'asterisk_cdr_user' in qs and 'asterisk_host' in qs and 'asterisk_port' in qs and 'asterisk_cmd_user' in qs and 'asterisk_cmd_secret' in qs:
			logging.info("Updating asterisk logins...")

			asteriskAuth = (str(qs['asterisk_host'][0]), str(qs['asterisk_port'][0]), str(qs['asterisk_cmd_user'][0]), str(qs['asterisk_cmd_secret'][0]), str(qs['asterisk_cdr_user'][0]), str(qs['asterisk_cdr_secret'][0]), str(qs['asterisk_version'][0]))
			
			if isAstValid(asteriskAuth):
				astValid = True
				asteriskUpdated = True # to tell mainloop() to reconnect.
				showMessage.add("AMI login details succesfully validated.")	
				logging.info("Asterisk logins updated.")
			else:
				astValid = False
				showMessage.add("AMI login details not correct.")
				logging.warning("Asterisk logins incorrect")
		elif 'asterisk_cdr_secret' in qs or 'asterisk_cdr_user' in qs or 'asterisk_host' in qs or 'asterisk_port' in qs or 'asterisk_cmd_user' in qs or 'asterisk_cmd_secret' in qs or 'asterisk_version' in qs:
			logging.warning("Only parts of Asterisk login data received.")
			showMessage.add("Please enter all data associated with the FreePBX installation you would like to connect to. Please refer to the README if you're unsure about this.")

		# Update Saleforce Data
		if 'sf_instance' in qs and 'sf_token' in qs and 'sf_password' in qs and 'sf_username' in qs:
			salesforceAuth = (str(qs['sf_instance'][0]), str(qs['sf_username'][0]), str(qs['sf_password'][0]), str(qs['sf_token'][0]))
			if updateSF(salesforceAuth):
				showMessage.add("SalesForce data succesfully updated.")
			else:
				showMessage.add("SalesForce could not be updated.")
		elif 'sf_instance' in qs or 'sf_token' in qs or 'sf_password' in qs or 'sf_username' in qs:
			logging.warning("Only parts of SF login received.")
			showMessage.add("Please enter all data associated with the SalesForce user would like to log-in with. Please refer to the README if you're unsure about this.")

		# Update SMTP Data
		if 'email_port' in qs and 'email_server' in qs and 'email_address' in qs and 'email_username' in qs and 'email_password' in qs:
			smtpAuth = (str(qs['email_server'][0]), str(qs['email_port'][0]), str(qs['email_address'][0]), str(qs['email_username'][0]), str(qs['email_password'][0]))
			smtpValid = True
			logging.info("smtp Data updated")
		elif 'email_port' in qs or 'email_server' in qs or 'email_address' in qs or 'email_username' in qs or 'email_password' in qs:
			logging.warning("Only parts of SMTP auth received.")
			showMessage.add("Please enter all data associated with the email address you would like to use.")

		# Add Shared User
		if 'addUser' in qs:
			for userId in qs['addUser']:
				if not userId in sharedUsers: # only if user not added as shared user, yet
					sharedUsers[userId] = []
					showMessage.add("Shared User added.")
				if not userId in emailUsers:
					emailUsers[userId] = True
				if not userId in voicemailUsers:
					voicemailUsers[userId] = True
				if not userId in unansweredUsers:
					unansweredUsers[userId] = True

		# Disable / Enabled Email Users:
		if 'emailEnabled' in qs:
			for userId in emailUsers:
				if userId in qs['emailEnabled']:
					emailUsers[userId] = True
				else:
					emailUsers[userId] = False

		# Disable / Enable Voicemail Users:
		if 'voicemailUsers' in qs:
			for userId in voicemailUsers:
				if userId in qs['voicemailUsers']:
					voicemailUsers[userId] = True
				else:
					voicemailUsers[userId] = False

		# Disable / Enable Unanswered Users:
		if 'unansweredUsers' in qs:
			for userId in unansweredUsers:
				if userId in qs['unansweredUsers']:
					unansweredUsers[userId] = True
				else:
					unansweredUsers[userId] = False

		# All user IDs in SalesForce begin with 005, so if there is a key beginning with 005, we assume it's a sharedUser and update the entry accordingly.
		sharedUsersGet = sliceDict(qs, '005')
		for sharedUserGet in sharedUsersGet:
			sharedUsers[sharedUserGet] = sharedUsersGet[sharedUserGet]

	if sfValid and astValid:
		extensions = sorted(getAllExtensions().iteritems(), key=lambda (k,v): v) # Sort by value (Name; put "k" to sort by the key, the extension)
		activeUsers = getActiveUsers()
		activeUsersNames = getUsersNames(activeUsers)
		usersForShared = sorted(activeUsers.iteritems(), key=lambda (k,v): v['Username']) # Sort users by Username
	else:
		extensions = None
		activeUsers = None
		activeUsersNames = None
		usersForShared = None

	render = render_template('template.html',
		showMessage = showMessage,
		sfValid = sfValid,
		astValid = astValid,
		extensions = extensions,
		activeUsersNames = activeUsersNames,
		sharedUsers = sharedUsers,
		activeUsers = activeUsers,
		emailUsers = emailUsers,
		voicemailUsers = voicemailUsers,
		unansweredUsers = unansweredUsers,
		loggingEnabled = loggingEnabled,
		usersForShared = usersForShared,
		savedConfigs = getSavedConfigs(),
		asteriskAuth = asteriskAuth,
		salesforceAuth = salesforceAuth,
		smtpAuth = smtpAuth,
		emailEnabled = emailEnabled
		)

	showMessage = set()

	logging.info("Time taken for request: " + str(time.time() - starttime))
	
	return render

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

	datafile = open(os.path.join(os.path.join(os.path.dirname(os.path.abspath(__file__))), str(filename)), 'wb')
	pickle.dump(encoder.seal(data), datafile)

def getAllExtensions():
	'''
	Returns all extensions registered in FreePBX as a dictionary in the format {'ext': 'Name'}
	'''
	global asteriskAuth
	# Initialise Telnet connection and log in.
	tn_ami = telnetlib.Telnet(asteriskAuth[0], asteriskAuth[1])
	tn_ami.read_until("Asterisk Call Manager/" + asteriskAuth[6])
	tn_ami.write("Action: Login\nUsername: " + asteriskAuth[2] + "\nSecret: " + asteriskAuth[3] + "\n\n")

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
	global lastAPIconnection
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
	global lastAPIconnection
	query = "SELECT Id FROM User WHERE Name LIKE '" + fullName + "'"
	result = sf.query_all(query)["records"]
	lastAPIconnection = time.time()
	if len(result) == 1:
		return result[0]['Id'] # return Id of first result
	else:
		return None

def getSavedConfigs():
	filenames = set()
	try:
		for filename in os.listdir(os.path.dirname(os.path.abspath(__file__))):
			if filename.endswith(".epk"):
				filenames.add(filename[:-4])
	except:
		logging.error("Could not list dir")
	return filenames

def getNumberTerm(phonenumber):
	'''
	Returns wildcarded version of phonenumber.
	Strips +/00 off of the beginning, and the next two digits to account for country codes
	'''

	if (phonenumber.startswith('0') and not phonenumber.startswith('00')):
		stripTwo = False
	else:
		stripTwo = True

	# Strip + or 00 or 0 off of phone number
	number = phonenumber.lstrip('+')
	number = number.lstrip('00')
	# Strip first 2 digits of phone number in case the CID (caller provider specific) includes a country code
	if stripTwo:
		number = number[2:len(number)]
	term = '%' # searchterm for salesfore SQOL
	for digit in number:
		term += (digit + "%")
	return term

def getNumberOfContacts(phonenumber):
	'''
	Returns the number of salesforce contacts associated with the phone number
	'''
	global lastAPIconnection
	term = getNumberTerm(phonenumber)

	results = sf.query_all("SELECT AccountId FROM Contact WHERE Phone LIKE '" + term + "' OR MobilePhone LIKE '" + term + "'")["records"]
	lastAPIconnection = time.time()
	return len(results)

def getNumberOfAccounts(phonenumber):
	'''
	Returns the number of salesforce contacts associated with the phone number
	'''
	global lastAPIconnection
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
	global lastAPIconnection
	term = getNumberTerm(phonenumber)
	#Query database for accounts
	results = sf.query_all("SELECT Id FROM Account WHERE Phone LIKE '" + term + "'")["records"]
	lastAPIconnection = time.time()
	if (len(results) == 1): # return ID of only match
		return results[0]['Id']
	else:
		try:
			# No Account found, looking for contacts
			results = sf.query_all("SELECT AccountId FROM Contact WHERE Phone LIKE '" + term + "'")["records"]
			lastAPIconnection = time.time()
			if (len(results) == 1): # return ID of only match
				return results[0]['AccountId']
			elif (len(results) == 0):
				# No Contact found; looking for mobiles
				results = sf.query_all("SELECT AccountId FROM Contact WHERE MobilePhone LIKE '" + term + "'")["records"]
				lastAPIconnection = time.time()
				if (len(results) == 1): # return ID of only match
					return results[0]['AccountId']
				else: # if multiple results, check if they belong to the same account
					accountId = results[0]['AccountId']
					for contact in results:
						if contact['AccountId'] != accountId:
							logging.warning("No unique account found")
							return None
					return accountId	
			else: # if multiple results, check if they belong to the same account
				accountId = results[0]['AccountId']
				for contact in results:
					if contact['AccountId'] != accountId:
						logging.warning("No unique account found")
						return None
				return accountId
		except:
			logging.warning("No unique account found")
			return None

def getContactId(phonenumber):
	'''
	Returns the Contact ID of the salesforce contact associated with the phone number
	'''
	global lastAPIconnection
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
	global smtpAuth
	global emailEnabled
	global lastAPIconnection
	if loggingEnabled:
		task = sf.Task.create({
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
		logging.info("\tCall logged. Task Id: " + str(task['id']) + ".")
		if emailEnabled and emailUsers[userId]:
			try:
				if sendEmail(userId, task['id'], smtpAuth): # Does not take into account shared Accounts.
					logging.info("\tEmail sent.")
			except:
				logging.warning("Email could not be sent.")
				showMessage.add("Check your email settings - Something seems to be wrong!")

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
	global asteriskAuth
	members = []
	# Initialise Telnet connection and log in.
	tn_ami = telnetlib.Telnet(asteriskAuth[0], asteriskAuth[1])
	tn_ami.read_until("Asterisk Call Manager/" + asteriskAuth[6])
	tn_ami.write("Action: Login\nUsername: " + asteriskAuth[2] + "\nSecret: " + asteriskAuth[3] + "\n\n")

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

def isAstValid(asteriskAuth):
	try:
		# Validate CMD user
		logging.debug("Validating CMD...")
		print asteriskAuth[0], type(asteriskAuth[0])
		print asteriskAuth[1], type(asteriskAuth[1])
		tnTest = telnetlib.Telnet(asteriskAuth[0], asteriskAuth[1], 10)
		tnTest.read_until("Asterisk Call Manager/" + asteriskAuth[6])
		tnTest.write("Action: Login\nUsername: " + asteriskAuth[2] + "\nSecret: " + asteriskAuth[3] + "\n\n")

		#Wait for fully booted
		tnTest.read_until("Status: Fully Booted")
		logging.info("AMI user validated")
		# Close Telnet connection
		tnTest.write("Action: Logoff" + "\n\n")
		tnTest.close()

		# Validate CDR user
		tnTest = telnetlib.Telnet(asteriskAuth[0], asteriskAuth[1], 10)
		tnTest.read_until("Asterisk Call Manager/" + asteriskAuth[6])
		tnTest.write("Action: Login\nUsername: " + asteriskAuth[4] + "\nSecret: " + asteriskAuth[5] + "\n\n")

		#Wait for fully booted
		tnTest.read_until("Status: Fully Booted")
		logging.info("AMI user validated")

		# Close Telnet connection
		tnTest.write("Action: Logoff" + "\n\n")
		tnTest.close()

		return True
	except:
		return False

def sendEmail(userId, taskId, smtpAuth):
	global salesforceAuth
	global showMessage
	server = smtplib.SMTP_SSL(host=smtpAuth[0], port=int(smtpAuth[1]))
	try:
		server.login(smtpAuth[3], smtpAuth[4])
	except:
		logging.warning("Could not send email; check SMTP log-in.")
		showMessage.add("Please update the email config; the data seems to be incorrect!")
		return

	msg = MIMEMultipart()
	msg['From'] = smtpAuth[2] #<- This will throw exception if no mail settings set
	msg['To'] = sf.User.get(userId)['Email']
	msg['Subject'] = 'Your call with ' + sf.Account.get(sf.Task.get(taskId)['WhatId'])['Name'] + '.'
	body = "Hi " + sf.User.get(userId)['FirstName'] + ",\nyou have just finished a call which has been logged in SalesForce.\n\nPlease update the entry with details about the call: http://" + salesforceAuth[0] + "/" + taskId + "/e.\n\n---- THIS IS AN AUTOMATICALLY GENERATED MESSAGE. ----"

	msg.attach(MIMEText(body, 'plain'))	
	server.sendmail(smtpAuth[2], msg['To'], msg.as_string())
	return True

communicatorThread = CommunicatorThread()
communicatorThread.start()

app.run(port=port)

breakCommunicatorThread = True
communicatorThread.join()