SF-FreePBX
==========

Log FreePBX/Asterisk calls in SalesForce and configure the extensions/users using an integrated web interface.

## Requirements

SF-FreePBX runs in environments with:
 
 * FreePBX (tested with 2.10.1.5)
 * SalesForce with API access enabled (Enterprise/Performance/Unlimited or Professional with Add-On)

The machine running SF-FreePBX requires
 * Python 2.7
 * telnet access to the PBX server on the port defined in the AMI configuration in Asterisk (default is 5038)

Names for the extensions need to be saved in the format `FirstName LastName` in FreePBX, and accordingly in SalesForce.

## Installation
### FreePBX

Two Asterisk Management Interface (*AMI*) users need to be configured on the PBX server. By default, the configuration file for this can be found at `/etc/asterisk/manager.conf`.
One user needs to have write-permissions for 'command', and the other one read-permissions for 'cdr'. Make sure they are accessible by the machine you are planning to run SF-FreePBX on.

SF-FreePBX is expecting the database keys for the cidnames in FreePBX to be formatted as `/AMPUSER/0000/cidname` where 0000 is the extension of the user.
The last name of the user in the cidname needs to be the same as the user's last name in SalesForce.

### Salesforce

You need a user with the permissions to create tasks (i.e. log calls/activity) on all accounts, and assign them to anyone. Note down the user's username, password and security token. If you don't have a record of the security token, you can reset it at
 1. Setup
 2. Under *Personal Setup*: My Personal Information
 3. Reset My Security token.

### SF-FreePBX

SF-FreePBX requires Python, [Simple-Salesforce](https://github.com/neworganizing/simple-salesforce/) and [EncryptedPickle for Python](https://github.com/vingd/encrypted-pickle-python).
Simple Salesforce can be installed with pip: `pip install simple-salesforce`, and so can EncryptedPickle: `pip install EncryptedPickle`.

## Set-Up & Run

Just run `python pbxSF.py` and configure the login details for FreePBX and SalesForce using the webinterface. By default this is accessible via http on port 8080. To specify your own port, run it with commandline argument `-p`.

If you are not loading a previously saved config, you will be asked to specify a log-in for the webinterface the first time you open it.

Your salesforce instance can be taken from the url when you are logged-in to . If it begins with `https://na1.salesforce.com`, for example, your instance would be `na1.salesforce.com`.

To load a previously saved config, you can use `-f filename -s passphrase`.
Take a look at the log to see if everything is running correctly.

## Configuration

The webinterface has several options. Please note that all changes made in the webinterface take effect immediately and no "Apply Config" or saving is needed.

#### Active Extensions

These are the extensions that are being monitored for calls. Note that it only shows extensions that could successfully matched to a SalesForce user using the Name.

#### Shared Users

In some environments, several people may share one SalesForce user account. In the `Options` you can specify any such accounts, and in the individual panel that is created you can choose the extensions that use this SalesForce account.
This function can also be used to assign a SalesForce user to an extensions manually. Simply select just a single extension for the user.

Please note that shared users are independent of the `Active Extensions` - whether or not an extension has been marked as active doesn't make a difference, so if you don't want to log calls made by users sharing an account or certain extensions associated with a Shared User, you should deselect the extensions or delete the Shared User. You can always use the `Save` and `Load` functions to restore a previous setting.

#### Enable/Disable logging

If logging is not enabled, the program will do all steps as usual, apart from actually recording the call in SalesForce. This can be useful to determine whether the program is running correctly without actually writing anything to the SalesForce database

#### Enable/Disable logging of unanswered calls

This allows you to stop logging incoming calls that have not been answered.

#### Save/Load
Save the current config permanently to the disk. This will be retained if the program is exited and restarted.
Use the Load function to load a previously saved config. All changes made since the last Save will be overridden.
Please note that the configs are encrypted by default - so please make sure you can remember the Passphrase!

##Security

Bear in mind that the connection between SF-FreePBX and Asterisk is plaintext, so binding the AMI users to a specific machine, tunneling the traffic or runninf SF-FreePBX on the Asterisk-Server is recommended.

## Extensions
If you would like to build on the code provided, here's an overview of the functions (despite the webserver)

    createTask(accountId, summary, userId, subject='Call', contactId=None)
        Creates new, completed "Call" task in SalesForce to show up in the account's Activity History
    
    getAccountId(phonenumber)
        Returns the Account ID of the salesforce account associated with the phone number
    
    getActiveUsers()
        Returns list of all active SalesForce Users
    
    getAllExtensions()
        Returns all extensions registered in FreePBX as a dictionary in the format {'ext': 'Name'}
    
    getContactId(phonenumber)
        Returns the Contact ID of the salesforce contact associated with the phone number
    
    getEventFieldValue(field, event)
        Returns value of field from cdr event as reported by the AMI.
        Event must be in the telnet format as string like "field: value\r\nfield:value\r\n"
    
    getNumberOfAccounts(phonenumber)
        Returns the number of salesforce contacts associated with the phone number
    
    getNumberOfContacts(phonenumber)
        Returns the number of salesforce contacts associated with the phone number
    
    getNumberTerm(phonenumber)
        Returns wildcarded version of phonenumber.
        Strips +/00 off of the beginning, and the next two digits to account for country codes
    
    getQueueMembers(extension)
        Returns list of extensions on given queue in FreePBX.
    
    getSharedUser(extension)
        Returns userId if extension is saved in config as a shared account.
        This needs to be done manually!
    
    getUserId(fullName)
        Returns the salesforce ID of the user with the matching name.
    
    getUsersNames(users)
        Returns list of all active SalesForce Users
    
    isLoggingEnabled(extension)
        Checks if logging is enabled for this extension.
    
    loadData(filename)
        Load previously saved data. Returns data as saved; usually tuple like (obj0, obj1, ...).
    
    mainloop()
        Main Function: Establishes connection to AMI and reads CDR events.
        Every 5 seconds, it checks if an event has been detected, and if so it checks whether
                - the call was inbound or outbound
                - the user is on a shared SalesForce account, and if not
                    - the user's extension is whitelisted (marked 'active' in the webinterface)
                - the phone number is registered with SalesForce (account or contact)
        If these tests validate, it logs the call in SalesForce as Activity (or 'Task') with relevant information, such as the duration and disposition, if configured.
    
    makeSummary(event)
        Returns string detailing duration and disposition of CDR event in 'event'.
    
    saveData(data, filename)
        Save data in filename using pickle. Give data as tuple like (obj0, obj1, ...).
    
    sliceDict(d, s)
        Return dictionary d only with keys starting with s
