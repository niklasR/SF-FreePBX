# Asterisk details
ASTERISK_HOST = "hostname"
ASTERISK_PORT = 5038
ASTERISK_CMD_USER = "user1"
ASTERISK_CMD_SECRET = "SECRET"
ASTERISK_CDR_USER = "user2"
ASTERISK_CDR_SECRET = "SECRET"

# SalesForce details
USERNAME = 'u@s.er'
PASSWORD = 'password'
TOKEN = 'T0K3N'
INSTANCE = 'instance.salesforce.com'

# This is in case a user's SalesForce name does not match up with their cidname or if multiple people share one SalesForce user.
SHARED_USERS = {'000000000000000':('wwww', 'xxxx'), '000000000000001':('zzzz', 'yyyy')}

# Restrict logging of calls to the following
LOGGING_BLACKLIST = ('0000', '1111')
LOGGING_WHITELIST = ('0000', '1111') # leave blank if you want to log all calls

# Restrict logging of unsanswered calls to the following
UNANSWERED_BLACKLIST = ('0000', '1111')
UNANSWERED_WHITELIST = ('0000', '1111') # leave blank if you want to log all calls