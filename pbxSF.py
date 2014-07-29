#! /usr/bin/env python
import sys, telnetlib, re, socket, time, datetime, pytz
from ast_login import *
from sf_login import *
from simple_salesforce import Salesforce

def getFullName(extension):
	'''
	Returns the Last Name of the user registered to the extensin in FreePBX.
	'''
	# Initialise Telnet connection and log in.
	tn_ami = telnetlib.Telnet(ASTERISK_HOST, ASTERISK_PORT)
	tn_ami.read_until("Asterisk Call Manager/1.1")
	tn_ami.write("Action: Login\nUsername: " + ASTERISK_AMI_USER + "\nSecret: " + ASTERISK_AMI_SECRET + "\n\n")

	# Wait for fully booted
	tn_ami.read_until("Status: Fully Booted")

	# Query for cidname from DB (FreePBX style)
	tn_ami.write("Action: Command\nCommand: database showkey " + extension + "/cidname\n\n")
	data = tn_ami.read_until("--END COMMAND--")
	
	# Analyse data to find last name
	if len(data) > 0:
		cidline = re.search('/AMPUSER/' + extension + '/cidname.+', data).group(0)
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

def getAccountId(phonenumber):
	'''
	Resturns the Account ID of the salesforce account associated with the phone number
	'''
	# Strip + or 00 off phone number
	phone = phonenumber.strip('+')
	phone = phone.strip('00')
	# Strip first 2 digits of phone number in case the CID (caller provider specific) includes a country code
	phone = phone[2:len(phone)]

	term = '%' # searchterm for salesfore SQOL
	for digit in phone:
		term += (digit + "%")
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
		'Summary__c':'Duration: ' + str(datetime.timedelta(seconds=duration))
		})
	lastAPIconnection = time.time()

def getEventFieldValue(field, event):
	'''
	Returns value of field from cdr event as reported by the AMI.
	Event must be in the telnet format as string like "field: value\r\nfield:value\r\n"
	'''
	pattern = field + ": .+"
	match = re.search(pattern, event)
	if match:
		line = match.group(0).split(" ")
		return ' '.join(line[1:len(line)]).strip("\r")
	else:
		return None

def main():
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
					if str(getEventFieldValue('DestinationContext', event)) == 'from-did-direct':
						print "\tInbound"
						salesforceAccount = getAccountId(getEventFieldValue('Source', event))
						if salesforceAccount:
							salesforceUser = getUserId(str(getFullName(getEventFieldValue('Destination', event))))
							if salesforceUser:
								print "\tSRC: " + getEventFieldValue('Source', event)
								print "\tSFA: " + salesforceAccount
								print "\tDST: " + getEventFieldValue('Destination', event)
								print "\tSFU: " + salesforceUser
								duration = getEventFieldValue('BillableSeconds', event)
								print "\tSEC: " + duration
								print "\tLogging Call in SalesForce..."
								createTask(salesforceAccount, int(duration), salesforceUser, "Inbound Call", None)
								print "\tLogged."
							else:
								print "\tNo associated SalesForce user found."
						else:
							print "\tNo associated SalesForce account found."
					elif str(getEventFieldValue('DestinationContext', event)) == 'from-internal':
						print "\tFrom Internal"
						salesforceAccount = getAccountId(getEventFieldValue('Destination', event))
						if salesforceAccount:
							salesforceUser = getUserId(str(getFullName(getEventFieldValue('Source', event))))
							if salesforceUser:
								print "\tSRC: " + getEventFieldValue('Source', event)
								print "\tSFA: " + salesforceAccount
								print "\tDST: " + getEventFieldValue('Destination', event)
								print "\tSFU: " + salesforceUser
								duration = getEventFieldValue('BillableSeconds', event)
								print "\tSEC: " + duration
								print "\tLogging Call in SalesForce..."
								createTask(salesforceAccount, int(duration), salesforceUser, "Outbound Call", None)
								#print "\t<TASK LOGGING SKIPPED FOR OUTBOUND CALLS>"
								print "\tLogged."
							else:
								print "\tNo associated SalesForce user found."
						else:
							print "\tNo associated SalesForce account found."
					else:
						print "\t" + str(getEventFieldValue('DestinationContext', event))
		# if last API call to SF older than 9 minutes make new API call to avoid session timeout
		if ((time.time()-(lastAPIconnection)) > (60*9)):
			print "Making Dummy Call to avoid SF session timeout..."
			sf.User.deleted(datetime.datetime.now(pytz.UTC) - datetime.timedelta(days=2), datetime.datetime.now(pytz.UTC))
			lastAPIconnection = time.time()
			print "Call made."
		time.sleep(5)

### START PROGRAM ###

lastAPIconnection = time.time()

# create logged in Salesforce Object
sf = Salesforce(instance=INSTANCE, username=USERNAME, password=PASSWORD, security_token=TOKEN)

if __name__ == "__main__":
	main()