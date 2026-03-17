#!/bin/bash
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
    CREATE DATABASE synapse
      ENCODING 'UTF8'
      LC_COLLATE='C'
      LC_CTYPE='C'
      TEMPLATE=template0;
EOSQL
