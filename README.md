SF-FreePBX
==========

Log FreePBX/Asterisk calls in SalesForce and configure the extensions/users using an integrated web interface.

## Requirements

SF-FreePBX runs in environments with:
 
 * FreePBX (tested with 2.10.1.5)
 * SalesForce with API access enabled (Enterprise/Performance/Unlimited or Professional with Add-On)

The machine running SF-FreePBX requires
 * Python 2.7
 * telnet access to the PBX server

Names for the extensions need to be saved in the format `$FirstName $LastName` in FreePBX, and accordingly in SalesForce.

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

SF-FreePBX requires Python and [Simple-Salesforce](https://github.com/neworganizing/simple-salesforce/).
Simple Salesforce can be installed with pip: `pip install simple-salesforce`.

## Set-Up

Fill out the config file `pbxSF_config.py` with the relevant details.
Your salesforce instance can be taken from the url when you are logged-in to . If it begins with `https://na1.salesforce.com`, for example, your instance would be `na1.salesforce.com`.

## Run

Just run `python pbxSF.py` and it should connect to Asterisk and SalesForce. Take a look at the log to see if everything is running correctly. You should be able to configure extensions using the webinterface at `http://localhost:PORT` (the port is specified in the config).

## Configuration

The webinterface has several options. Please note that all changes made in the webinterface take effect immediately and no "Apply Config" or saving is needed.

#### Active Extensions

These are the extensions that are being monitored for calls. Note that it only shows extensions that could successfully matched to a SalesForce user using the Name.

#### Shared Users

In some environments, several people may share one SalesForce user account. In the `Options` you can specify any such accounts, and in the individual panel that is created you can choose the extensions that use this SalesForce account.
This function can also be used to assign a SalesForce user to an extensions manually. Simply select just a single extension for the user.

Please note that shared users are independent of the `Active Extensions` - whether or not an extension has been marked as active doesn't make a difference, so if you don't want to log calls made by users sharing an account or certain extensions associated with a Shared User, you should deselect the extensions or delete the Shared User. You can always use the `Save` and `Load` functions to restore a previous setting.

#### Enable/Disable logging

If logging is not enabled, the program will do all steps as usual, apart from actually recording the call in SalesForce. This can be useful to determine whether the program is running correctly without actually writing to the SalesForce database

#### Enable/Disable logging of unanswered calls

This allows you to stop logging incoming calls that have not been answered.

#### Save/Load
Save the current config permanently to the disk. This will be retained if the program is exited and restarted.
Use the Load function to load a previously saved config. All changes made since the last Save will be overridden.

##Security

Bear in mind that the connection between SF-FreePBX and Asterisk is plaintext, so binding the AMI users to a specific machine, tunneling the traffic or runninf SF-FreePBX on the Asterisk-Sever is recommended.
