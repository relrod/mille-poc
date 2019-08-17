#!/usr/bin/env python

import boto3
from collections import defaultdict
import configparser
import sys

class MilleClient():
    def __init__(self, key_id, key_secret, pool):
        self.client = boto3.client(
            'cognito-idp',
            aws_access_key_id=key_id,
            aws_secret_access_key=key_secret)
        # groupname: [user]
        self.groups = {}

        # username: user
        self.users = {}

        # username: [groupname]
        self.users_groups = defaultdict(set)

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
                    self.users_groups[user['Username']].add(group)
                    if user['Username'] not in self.users:
                        self.users[user['Username']] = user

    def generate_group_text(self, gid, name):
        linesuffix = '%s:x:%s:' % (name, uid)
        text = '=%s %s\n0%i %s\n.%s %s\n' % (
            gid,
            linesuffix,
            self.group_i,
            linesuffix,
            name,
            linesuffix)
        self.group_i += 1
        return text

    def generate_user_text(self, uid, username, name, shell, home_dir):
        linesuffix = '%s:x:%s:%s:%s:%s:%s' % (
            username,
            uid,
            uid,
            name,
            home_dir,
            shell)
        text = '=%s %s\n0%i %s\n.%s %s\n' % (
            uid,
            linesuffix,
            self.passwd_i,
            linesuffix,
            username,
            linesuffix)
        self.passwd_i += 1
        return text

    def generate_shadow_text(self, uid, username):
        linesuffix = '%s:*::::7:::' % username
        text = '=%s %s\n0%i %s\n.%s %s\n' % (
            uid,
            linesuffix,
            self.shadow_i,
            linesuffix,
            username,
            linesuffix)
        self.shadow_i += 1
        return text

def get_attr(user, attr):
    attr_filter = list(
        filter(
            lambda x: x['Name'] == attr,
            user['Attributes']))
    if len(attr_filter) == 0:
        sys.stderr.write(
            'WARNING! No %s attribute found for %s\n' %
            (attr, user['Username']))
        return None
    return attr_filter[0]['Value']
    
if __name__ == '__main__':
    config = configparser.ConfigParser()
    config.read('conf.ini')

    # TODO: use .get or whatever to make this fail better
    groups_with_access = set(
        config['mille']['groups_with_access_to_this_system'].split(','))

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

    # Groups

    with open(config['mille']['group_file'], 'w') as f:
        # User-groups
        for username, user in mc.users.items():
            if username.startswith('g:'):
                continue
            # There has got to be a better way to do this:
            uid = get_attr(user, 'custom:uid')
            if not uid:
                continue
            f.write(mc.generate_group_text(int(uid), username))

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
            gid = get_attr(g_user, 'custom:uid')
            if not gid:
                continue
            f.write(mc.generate_group_text(int(gid), groupname))

    with open(config['mille']['passwd_file'], 'w') as f:
        for username, user in mc.users.items():
            if username.startswith('g:'):
                continue
            uid = get_attr(user, 'custom:uid')
            name = get_attr(user, 'name')
            if not uid:
                continue

            # If there's at least one group in common between the user's groups
            # and the groups with access to the system, then we can create the
            # passwd entry for the user.
            if len(
                    groups_with_access.intersection(
                        mc.users_groups[username])) > 0:
                shell = config['mille']['shell']
                home_dir = config['mille']['home_dir_prefix'] + username
                f.write(mc.generate_user_text(
                    int(uid),
                    username,
                    name,
                    shell,
                    home_dir))

    with open(config['mille']['shadow_file'], 'w') as f:
        for username, user in mc.users.items():
            if username.startswith('g:'):
                continue
            uid = get_attr(user, 'custom:uid')
            name = get_attr(user, 'name')
            if not uid:
                continue

            # If there's at least one group in common between the user's groups
            # and the groups with access to the system, then we can create the
            # shadow entry for the user.
            if len(
                    groups_with_access.intersection(
                        mc.users_groups[username])) > 0:
                f.write(mc.generate_shadow_text(
                    int(uid),
                    username))
