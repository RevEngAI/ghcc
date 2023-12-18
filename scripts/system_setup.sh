#!/usr/bin/env bash

# setup an ubuntu machine as the primary controller for this pipeline.

# bypass any requests for user input during package installation
DEBIAN_FRONTEND=noninteractive
# add this file to prevent any configuration related to local system time
sudo ln -fs /usr/share/zoneinfo/Europe/Ldon /etc/localtime
sudo apt update && sudo apt install -y \
    ca-certificates \
    curl \
    gnupg \
    python3 \
    python3-pip \
    python-is-python3

# Add Docker's official GPG key:
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Add the repository to Apt sources:
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update

# install docker from system packages
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# docker post-install changes so you can run it without sudo
sudo usermod -aG docker $USER

# newgrp docker

# add mongo db pgp key
curl -fsSL https://pgp.mongodb.com/server-7.0.asc | sudo gpg -o /usr/share/keyrings/mongodb-server-7.0.gpg --dearmor
# add mongodb to apt sources
echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse" | sudo tee /etc/apt/sources.list.d/mongodb-org-7.0.list
sudo apt update

# install latest version of mongodb from apt
sudo apt install -y mongodb-org
# start the mongodb service so the tool can connect to it
sudo systemctl start mongod
# init the db
mongosh <<EOF
use admin
db.createUser({
  user: 'gchh_crawler',
  pwd: 'securepassword',
  roles: [{ role: 'readWrite', db: 'ghcc' }]
})
use ghcc
EOF

pip install -r requirements.txt

# copying instead of using 'mv' just to have a backup
cp database-config-example.json database-config.json

# build the docker container for building projects
docker build -t gcc-custom .