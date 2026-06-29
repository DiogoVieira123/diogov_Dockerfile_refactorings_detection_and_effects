#!/bin/sh
# Extracted setup logic (was previously inline in a RUN instruction)
mkdir -p /app/data /app/logs /app/config
cp /app/app.txt /app/data/app.txt
echo "setup step 1 done" >> /app/logs/setup.log
echo "setup step 2 done" >> /app/logs/setup.log
echo "setup step 3 done" >> /app/logs/setup.log
chmod -R 755 /app/data
rm -f /app/app.txt
