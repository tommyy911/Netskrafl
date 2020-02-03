@ECHO OFF
ECHO Deploy an update to App Server
set GOOGLE_APPLICATION_CREDENTIALS=resources\netskrafl-0dd9fbdf9ab3.json
:CHECKS
IF /i "%1" EQU "SKRAFLSTATS" GOTO STATS
IF /i "%1" EQU "STATS" GOTO STATS
IF /i "%1" EQU "S" GOTO STATS
IF /i "%1" EQU "INDEXES" GOTO INDEXES
IF /i "%1" EQU "IX" GOTO INDEXES
IF /i "%1" EQU "I" GOTO INDEXES
IF /i "%1" EQU "CRON" GOTO CRON
IF /i "%1" EQU "C" GOTO CRON
IF /i "%1" EQU "DEFAULT" GOTO DEFAULT
IF /i "%1" EQU "D" GOTO DEFAULT
ECHO Full deployment (app + skraflstats) starting
cmd.exe /c "grunt make"
ECHO *** Currently disabled ***
ECHO Full deployment completed
GOTO :EOF
:DEFAULT
ECHO Default module deployment (app) starting
cmd.exe /c "grunt make"
gcloud beta app deploy --version=newdb --no-promote --project=netskrafl app.yaml
ECHO Default module deployment completed
GOTO :EOF
:INDEXES
ECHO Index update starting
ECHO *** Currently disabled ***
ECHO Index update completed
GOTO :EOF
:CRON
ECHO Cron update starting
ECHO *** Currently disabled ***
ECHO Cron update completed
GOTO :EOF
:STATS
ECHO Skraflstats deployment starting
ECHO *** Currently disabled ***
ECHO Skraflstats deployment completed
GOTO :EOF
:EOF
