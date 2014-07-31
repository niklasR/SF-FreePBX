#! /usr/bin/env python
import sys, telnetlib, re, socket, time, datetime, pytz
from pbxSF_config import *
from simple_salesforce import Salesforce

def getFullName(extension):
	'''
	Returns the Last Name of the user registered to the extensin in FreePBX.
	'''
	# Initialise Telnet connection and log in.
	tn_ami = telnetlib.Telnet(ASTERISK_HOST, ASTERISK_PORT)
	tn_ami.read_until("Asterisk Call Manager/1.1")
	tn_ami.write("Action: Login\nUsername: " + ASTERISK_CMD_USER + "\nSecret: " + ASTERISK_CMD_SECRET + "\n\n")

	# Wait for fully booted
	tn_ami.read_until("Status: Fully Booted")

	# Query for cidname from DB (FreePBX style)
	tn_ami.write("Action: Command\nCommand: database showkey " + extension + "/cidname\n\n")
	data = tn_ami.read_until("--END COMMAND--")
	
	# Analyse data to find last name
	if len(data) > 0:
		match = re.search('/AMPUSER/' + extension + '/cidname.+', data)
		if match:
			cidline = match.group(0)
		else:
			return None
		words = re.findall('\w+', cidline)
		fullname = " ".join(words[3:len(words)]) # last 'word' in cidline

	# Close Telnet connection
	tn_ami.write("Action: Logoff" + "\n\n")
	tn_ami.close()

	return fullname

def getUserId(fullName):
	'''
	Returns the salesforce ID of the user with the matching last name.
	'''
	query = "SELECT Id FROM User WHERE Name LIKE '" + fullName + "'"
	result = sf.query_all(query)["records"]
	lastAPIconnection = time.time()
	if len(result) == 1:
		return result[0]['Id'] # return Id of first result
	else:
		return None

def getNumberTerm(phonenumber):
	'''
	Returns wildcarded version of phonenumber.
	Strips +/00 of the beginning, and the next two digits to account for country codes
	'''
	# Strip + or 00 off phone number
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
	Resturns the number of salesforce contacts associated with the phone number
	'''
	term = getNumberTerm(phonenumber)

	results = sf.query_all("SELECT AccountId FROM Contact WHERE Phone LIKE '" + term + "' OR MobilePhone LIKE '" + term + "'")["records"]
	lastAPIconnection = time.time()
	return len(results)

def getNumberOfAccounts(phonenumber):
	'''
	Resturns the number of salesforce contacts associated with the phone number
	'''
	term = getNumberTerm(phonenumber)

	results = sf.query_all("SELECT Id FROM Account WHERE Phone LIKE '" + term + "'")["records"]
	lastAPIconnection = time.time()
	if (len(results) > 0): # return ID of only match
		return len(results)
	else:
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
	Resturns the Account ID of the salesforce account associated with the phone number
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
	Resturns the Contact ID of the salesforce contact associated with the phone number
	'''
	term = getNumberTerm(phonenumber)
	#Query database for accounts
	results = sf.query_all("SELECT Id FROM Contact WHERE Phone LIKE '" + term + "' OR MobilePhone LIKE '" + term + "'")["records"]
	lastAPIconnection = time.time()
	if (len(results) == 1): # return ID of only match
		return results[0]['Id']
	return None

def createTask(accountId, duration, userId, subject='Call', contactId=None):
	'''
	Creates new, completed "Call" task in SalesForce to show up in the account's Activity History
	'''
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
		'Summary__c':'Duration: ' + str(datetime.timedelta(seconds=duration)),
		'ActivityDate':time.strftime('%Y-%m-%d')
		})
	lastAPIconnection = time.time()

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
			match = re.search('\(Local/\d{4}', line) # Assuming queue entries are like '*(Local/1339*' and only queue members are
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
	for i in SHARED_USERS:
		if extension in SHARED_USERS[i]:
			return i
	return None

def main():
	'''
	Main Function: Establishes connection to AMI and reads CDR events.
	Every 5 seconds, it checks if an event has been detected, and if so it checks whether
		- the call was inbound or outbound
		- the user is on a shared SalesForce account (support), and if not
			- the user is registered with SalesForce
		- the phone number is registered with SalesForce (account or contact)
	If these tests validate, it logs the call in SalesForce as Activity (or 'Task') with relevant information.
	'''
	global lastAPIconnection
	# Initialise Telnet connection and log in.
	tn_cdr = telnetlib.Telnet(ASTERISK_HOST, ASTERISK_PORT)
	tn_cdr.read_until("Asterisk Call Manager/1.1")
	tn_cdr.write("Action: Login\nUsername: " + ASTERISK_CDR_USER + "\nSecret: " + ASTERISK_CDR_SECRET + "\n\n")

	#Wait for fully booted
	tn_cdr.read_until("Status: Fully Booted")
	print "FULLY BOOTED, starting loop"
	# Infinite loop for continuous AMI communication
	while True:
		data = tn_cdr.read_very_eager()
		if len(data) > 0:
			events = data.split("\r\n\r\n")
			for event in events:
				if str(getEventFieldValue('Event', event)) == 'Cdr':
					print "CDR logged:"
					# Inbound calls to Extension
					if str(getEventFieldValue('DestinationContext', event)) == 'from-did-direct':
						print "\tInbound"
						# Check if extension is saved as shared User in config
						salesforceUser = getSharedUser(getEventFieldValue('Destination', event))
						# If not saved, check if extension matches any SalesForce user
						if not salesforceUser:
							localName = getFullName(getEventFieldValue('Destination', event))
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
							duration = getEventFieldValue('BillableSeconds', event)
							numberOfContacts = getNumberOfContacts(getEventFieldValue('Source', event))

							if (numberOfContacts != 1): # 0 or 2+ contacts associated with phone number
								numberOfAccounts = getNumberOfAccounts(getEventFieldValue('Source', event))
								if (numberOfAccounts == 0):
									print "\tNo associated SalesForce account found."
								elif(numberOfAccounts == 1):
									salesforceAccount = getAccountId(getEventFieldValue('Source', event))
									print "\tSRC: " + getEventFieldValue('Source', event) + "\n\tSFA: " + salesforceAccount + "\n\tDST: " + getEventFieldValue('Destination', event) + "\n\tSFU: " + salesforceUser + "\n\tSEC: " + duration + "\n\tLogging Call in SalesForce..."
									createTask(salesforceAccount, int(duration), salesforceUser, "Call Inbound; Contact unknown", None)
									print "\tLogged."
								elif(numberOfAccounts > 1):
									print "\t" + str(numberOfAccounts) + " accounts found. No exact match possible." 
							else: # exact contact match
								salesforceAccount = getAccountId(getEventFieldValue('Source', event))
								salesforceContact = getContactId(getEventFieldValue('Source', event))
								duration = getEventFieldValue('BillableSeconds', event)
								print "\tSRC: " + getEventFieldValue('Source', event) + "\n\tSFA: " + salesforceAccount + "\n\tSFC: " + salesforceContact + "\n\tDST: " + getEventFieldValue('Destination', event)  + "\n\tSFU: " + salesforceUser + "\n\tSEC: " + duration + "\n\tLogging Call in SalesForce..."
								createTask(salesforceAccount, int(duration), salesforceUser, "Call Inbound", salesforceContact)
								print "\tLogged."

						else:
							print "\tNo associated SalesForce user found."

					# Call From Internal
					elif str(getEventFieldValue('DestinationContext', event)) == 'from-internal':
						print "\tFrom Internal"
						if (len(str(getEventFieldValue('Destination', event))) > 4):
							# Check if extension is saved as shared User in config
							salesforceUser = getSharedUser(getEventFieldValue('Source', event))
							# If not saved, check if extension matches any SalesForce user
							if not salesforceUser:
								localName = getFullName(getEventFieldValue('Source', event))
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
								duration = getEventFieldValue('BillableSeconds', event)
								numberOfContacts = getNumberOfContacts(getEventFieldValue('Destination', event))
								if (numberOfContacts != 1): # 0 or 2+ contacts associated with phone number
									numberOfAccounts = getNumberOfAccounts(getEventFieldValue('Destination', event))
									if (numberOfAccounts == 0):
										print "\tNo associated SalesForce account found."
									elif(numberOfAccounts == 1):
										salesforceAccount = getAccountId(getEventFieldValue('Destination', event))
										print "\tSRC: " + getEventFieldValue('Source', event) + "\n\tSFA: " + salesforceAccount + "\n\tDST: " + getEventFieldValue('Destination', event) + "\n\tSFU: " + salesforceUser + "\n\tSEC: " + duration + "\n\tLogging Call in SalesForce..."
										createTask(salesforceAccount, int(duration), salesforceUser, "Call Outbound; Contact unknown", None)
										print "\tLogged."
									elif(numberOfAccounts > 1):
										print "\t" + str(numberOfAccounts) + " accounts found. No exact match possible." 
								else: # exact contact match
									salesforceAccount = getAccountId(getEventFieldValue('Destination', event))
									salesforceContact = getContactId(getEventFieldValue('Destination', event))
									duration = getEventFieldValue('BillableSeconds', event)
									print "\tSRC: " + getEventFieldValue('Source', event) + "\n\tSFA: " + salesforceAccount + "\n\tSFC: " + salesforceContact + "\n\tDST: " + getEventFieldValue('Destination', event) + "\n\tSFU: " + salesforceUser + "\n\tSEC: " + duration + "\n\tLogging Call in SalesForce..."
									createTask(salesforceAccount, int(duration), salesforceUser, "Call Outbound", salesforceContact)
									print "\tLogged."

							else:
								print "\tNo associated SalesForce user found."
						else:
							print "\tExtension dialled."
					else:
						print "\t" + str(getEventFieldValue('DestinationContext', event))

		# if last API call to SF older than 9 minutes make new API call to avoid session timeout
		if ((time.time()-(lastAPIconnection)) > (60*9)):
			print "Making dummy API call to avoid SF session timeout..."
			sf.User.deleted(datetime.datetime.now(pytz.UTC) - datetime.timedelta(days=2), datetime.datetime.now(pytz.UTC))
			lastAPIconnection = time.time()
			print "API call made."
		
		time.sleep(5)

### START PROGRAM ###

lastAPIconnection = time.time()

# create logged in Salesforce Object
sf = Salesforce(instance=INSTANCE, username=USERNAME, password=PASSWORD, security_token=TOKEN)

if __name__ == "__main__":
	main()