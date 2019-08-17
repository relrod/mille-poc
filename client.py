#!/usr/bin/env python

import boto3
from collections import defaultdict
import configparser
import sys

groups_with_access_to_this_system = ['sysadmin-apples', 'fruit-sig']

class MilleClient():
    def __init__(self, key_id, key_secret, pool):
        self.client = boto3.client(
            'cognito-idp',
            aws_access_key_id=key_id,
            aws_secret_access_key=key_secret)
        self.groups = {}
        self.users = {}
        self.pool = pool

        # Global state for generating passwd/group/shadow dbs.
        # We need to keep track of indexes/entry numbers
        self.group_i = 0
        self.passwd_i = 0
        self.shadow_i = 0

    def debug(self):
        print('Groups: %s' % self.groups)
        print('Users: %s' % self.users)

    def store_groups(self):
        paginator = self.client.get_paginator('list_groups')
        pages = paginator.paginate(UserPoolId=self.pool)
        for page in pages:
            for group in page['Groups']:
                self.groups[group['GroupName']] = []

    def store_users_in_group(self, group):
        paginator = self.client.get_paginator('list_users_in_group')
        pages = paginator.paginate(
            UserPoolId=self.pool,
            GroupName=group)
        for page in pages:
            for user in page['Users']:
                if user['Enabled']:
                    self.groups[group].append(user)
                    self.users[user['Username']] = user
                    if user['Username'] not in self.users:
                        self.users[user['Username']] = user

    def generate_group_text(self, gid, name):
        linesuffix = '%s:x:%s:' % (name, uid)
        text = '=%s %s\n0%i %s\n.%s %s' % (
            gid,
            linesuffix,
            self.group_i,
            linesuffix,
            name,
            linesuffix)
        self.group_i += 1
        return text

def get_uid(user):
    uid_attr = list(
        filter(
            lambda x: x['Name'] == 'custom:uid',
            user['Attributes']))
    if len(uid_attr) == 0:
        sys.stderr.write(
            'WARNING! No uid found for %s\n' % user['Username'])
        return None
    return uid_attr[0]['Value']
    
if __name__ == '__main__':
    config = configparser.ConfigParser()
    config.read('conf.ini')
    mc = MilleClient(
        config['mille']['aws_key'],
        config['mille']['aws_secret'],
        config['mille']['user_pool'])

    # Load the list of all groups
    mc.store_groups()

    # Populate each group with the list of its user objects/members
    #for group in groups_with_access_to_this_system:
    #
    # Actually, we need to do this for EVERY group because we want to show
    # membership for all groups for all users, not just ones which gave them
    # access.
    for group in mc.groups.keys():
        mc.store_users_in_group(group)

    # User-groups
    for username, user in mc.users.items():
        if username.startswith('g:'):
            continue
        # There has got to be a better way to do this:
        uid = get_uid(user)
        if not uid:
            continue
        print(mc.generate_group_text(int(uid), username))

    # Actual groups.
    # The 'gid' comes from the 'uid' of the *user* called 'g:groupname'
    for groupname, group in mc.groups.items():
        g_user = mc.users.get('g:%s' % groupname)
        if not g_user:
            sys.stderr.write(
                "WARNING! No user `%s' found: Could not look up group gid.\n" %
                'g:%s' % groupname)
            continue
        # There has got to be a better way to do this:
        gid = get_uid(g_user)
        if not gid:
            continue
        print(mc.generate_group_text(int(gid), groupname))
