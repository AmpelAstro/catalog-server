#!/usr/bin/env bash

MONGODUMP_DIR=/docker-entrypoint-initdb.d
MONGO_USER=nobody
MONGO_PASSWORD=seekrit

# build a quoted string of catalog names
catalogs=\"$(find $MONGODUMP_DIR/ -maxdepth 1 -mindepth 1 -type d -exec basename {} \; | xargs echo)\"
# munge into list of js objects
roles=$(echo $catalogs | jq 'split(" ") | [{db : .[], role : "read"}]')
echo $roles

mongo=( mongo --host 127.0.0.1 --port 27017 --username $MONGO_INITDB_ROOT_USERNAME --password $MONGO_INITDB_ROOT_PASSWORD --authenticationDatabase admin )
"${mongo[@]}" admin <<-EOJS
	db.runCommand({ createRole: "listDatabases",
		privileges: [
			{ resource: { cluster : true }, actions: ["listDatabases"]}
			],
		roles: []
	})
	db.createUser({
		user: $(_js_escape "$MONGO_USER"),
		pwd: $(_js_escape "$MONGO_PASSWORD"),
		roles: $roles
	})
	db.grantRolesToUser($(_js_escape "$MONGO_USER"), [{"role": "listDatabases", "db": "admin"}])
	db.grantRolesToUser($(_js_escape "$MONGO_USER"), [{"role": "read", "db": "ToO"}])
EOJS

restore=( mongorestore --host 127.0.0.1 --port 27017 --username $MONGO_INITDB_ROOT_USERNAME --password $MONGO_INITDB_ROOT_PASSWORD --authenticationDatabase admin )
find $MONGODUMP_DIR/ -maxdepth 1 -mindepth 1 -type d -exec basename {} \; | xargs -L1 -iTARGET ${restore[@]} -d TARGET $MONGODUMP_DIR/TARGET
