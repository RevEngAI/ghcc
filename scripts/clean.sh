#!/usr/bin/env bash

./purge_folder.py archives/
./purge_folder.py repos/
./purge_folder.py binaries/

python -m ghcc.database clear
