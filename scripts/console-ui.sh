#!/bin/bash


OMNIPY_HOME="/home/pi/omnipy"



function DoBackup(){

	cd $OMNIPY_HOME/../
        backupfilename="omnipy_backup_"$(date +%d-%m-%y-%H%M%S)".tar.gz omnipy"
	name=$(whiptail --title "Backup Omnipy setup" --inputbox "What backup file name do you want ?" 10 60 $backupfilename 3>&1 1>&2 2>&3)
 	exitstatus=$?
	if [ $exitstatus = 0 ]; then
		tar -cvzf $name
		echo "Backup done"
	else
		echo "No Backup requested"
	fi
}

function UpdateOmnipy(){


	if(whiptail --title "Update Omnipy" --yesno "Do you want to backup the current Omnipy setup on your pi ?" 8 45)
        then
        	DoBackup
        fi

	cd $OMNIPY_HOME
	git stash
	git pull -f
	bash $OMNIPY_HOME/scripts/pi-update.sh
}

function NewPODActivation(){


	TimeOffset='date +"%:z"'
	TimeOffsetMin=120 #to be done and updated in the formula below
	StartingBasal=0.05


	if (whiptail --title "Activate new POD" --yesno "Have you already filled the new pod and heard the 2 bips ?" 15 80)
	then
 		cd $OMNIPY_HOME
		UserTimeOffset=$(whiptail --title "Activate new POD" --inputbox "Please confirm your timezone offset from GMT in MINUTES.\n\nIt can be a negative number !!!" 10 60 $TimeOffsetMin 3>&1 1>&2 2>&3)
		exitstatus=$?
	        if [ $exitstatus = 0 ]
		then
        		whiptail --title "Activate new POD" --msgbox "Please wait until the POD is fully primed." 15 60
			./omni.py activate $UserTimeOffset

			whiptail --title "Activate new POD" --msgbox "Once the POD is fully primed, place it on your body" 15 80

			UserStartingBasal=$(whiptail --title "Activate new POD" --inputbox "Please confirm your starting basal rate" 10 60 $StartingBasal 3>&1 1>&2 2>&3)
	                exitstatus=$?
	                if [ $exitstatus = 0 ]
			then
				./omni.py start $UserStartingBasal

				READPDM=$(./omni.py readpdm)
        		        echo $READPDM
                		STATUS=$(echo $READPDM | jq .success)
                		echo $STATUS

				if [ $STATUS == "true" ]
				then
					whiptail --title "Activate new POD" --msgbox "POD up and running" 15 80
					MainMenu
				else
					 whiptail --title "Activate new POD" --msgbox "A problem occured" 15 80
				fi
			else
				whiptail --title "Activate new POD" --msgbox "A problem occured" 15 80
			fi
	        else
        	        echo "Activation aborted"
			MainMenu
	      	fi
	else
		whiptail --title "POD Activation" --msgbox "Activation aborted !" 10 60
		MainMenu
	fi

}


function PODDeactivation(){

	if (whiptail --title "POD Deactivation?" --yesno "Are you sure you want to deactivate your POD ?" 10 60) then
	        cd $OMNIPY_HOME
		echo "POD deactivation"
		DEACTIVATE=$(./omni.py deactivate) #to be changed by ./omni.py archive
		echo $DEACTIVATE
		STATUS=$(echo $DEACTIVATE | jq .success)
		if [ $STATUS == "true" ]
		then
			whiptail --title "POD Deactivation" --msgbox "POD Deactivation Succeeded" 15 80
		else
			whiptail --title "POD Deactivation" --msgbox "Deactivation Failed" 15 80
		fi
        else
		whiptail --title "POD Deactivation" --msgbox "POD deactivation cancelled" 10 60
                echo "Deactivation cancelled"
       fi
}


function ConfigureRPi(){
	sudo raspi-config
	MainMenu
}


function ConfigureBT(){
    sudo systemctl stop omnipy-pan.service
    sudo systemctl disable omnipy-pan.service
    echo "Removing existing bluetooth devices"
    sudo btmgmt power on
    sudo bt-device -l | grep -e \(.*\) --color=never -o| cut -d'(' -f2 | cut -d')' -f1 | while read -r mac
    do
            if [ !mac ]; then
                    sudo bt-device -d $mac
                    sudo bt-device -r $mac
            fi
    done
    echo
    echo "Activating bluetooth pairing mode"
    sudo btmgmt connectable yes
    sudo btmgmt discov yes
    sudo btmgmt pairable yes
    sudo killall bt-agent
    sudo bt-agent -c NoInputNoOutput -d
    echo "Bluetooth device is now discoverable"
    echo
    echo "Open ${bold}bluetooth settings${normal} on your phone to search for and ${bold}pair${normal} with this device"
    echo "If you have already paired it on your phone, please unpair it first, then pair again"
    echo
    printf "Waiting for connection.."

    btdevice=
    while [[ -z "$btdevice" ]]
    do
            printf "."
            sleep 1
            btdevice=`sudo bt-device -l | grep -e \(.*\)`
    done

    sudo btmgmt discov no

    echo

    echo "${bold}Paired with $btdevice.${normal}"
    mac=`echo $btdevice | cut -d'(' -f2 | cut -d')' -f1`

    echo
    echo
    echo "Please ${bold}enable bluetooth tethering${normal} on your phone if it's not already enabled"
    echo "Waiting for connection."
    echo "addr=$mac" > /home/pi/omnipy/scripts/btnap-custom.sh
    cat /home/pi/omnipy/scripts/btnap.sh >> /home/pi/omnipy/scripts/btnap-custom.sh
    sudo cp /home/pi/omnipy/scripts/omnipy-pan.service /etc/systemd/system/
    sudo systemctl enable omnipy-pan.service
    sudo systemctl start omnipy-pan.service
    ipaddr=
    while [[ -z "$ipaddr" ]]
    do
            printf "."
            sleep 1
            ipaddr=`sudo ip -o -4 address | grep bnep0 | grep -e inet.*/ -o | cut -d' ' -f2 | cut -d'/' -f1`
    done
    echo
    echo
    echo "${bold}Connection test succeeeded${normal}. IP address: $ipaddr"

}





function DeveloperMenu(){
		echo "Developer Menu"
		SUBOPTION=$(whiptail --title "Advanced Settings" --menu "Choose the action you want to perform" --cancel-button "Back" 20 80 11 \
			"1" "Rig status" \
			"2" "View POD.log" \
			"3" "View omnipy.log" \
			"4" "Stop Services" \
			"5" "Restart Services" \
			"6" "Check RileyLink" \
			"7" "Configure Bluetooth" \
			"8" "Reset REST-API password" \
			"9" "Backup current Omnipy config" \
			"10" "Restore Omnipy backup" \
			"11" "Enable/Disable menu at SSH login"  3>&1 1>&2 2>&3)

		exitstatus=$?
		if [ $exitstatus -ne 0 ]; then MainMenu; fi;


		case $SUBOPTION in
			1)
				cd $OMNIPY_HOME
				echo "processing status..."
				RigStatus=$(./omni.py status)
				echo $RigStatus >> rigstatus.txt
				vim -R rigstatus.txt
				rm rigstatus.txt
				DeveloperMenu
			;;

			2)
				vim -R  ~/omnipy/data/pod.log
				DeveloperMenu
			;;

			3)
				vim -R ~/omnipy/data/omnipy.log
				DeveloperMenu
			;;

			4)
				echo "Stop services"
				sudo systemctl stop omnipy-rest.service
				sudo systemctl stop omnipy-beacon.service
				sudo systemctl stop omnipy-pan.service
				
				Services_Status=

				if $(systemctl -q is-active omnipy-rest.service)
				then
 					Services_Status="Failed: Omnipy Service has not been stopped\n"
				else
					Services_Status="Success: Omnipy Service has been stopped successfully\n"
				fi


				if $(systemctl -q is-active omnipy-beacon.service)
				then
                                        Services_Status+="Failed: Omnipy-beacon Service has not been stopped\n"
                                else
                                        Services_Status+="Success: Omnipy-beacon Service has been stopped successfully\n"
                                fi


				if $(systemctl -q is-active omnipy-pan.service)
				then
                                        Services_Status+="Failed: Omnipy-pan Service has not been stopped"
                                else
                                        Services_Status+="Success: Omnipy-pan Service has been stopped successfully"
                                fi

				whiptail --title "Omnipy Services stop " --msgbox "$Services_Status" 10 80
				DeveloperMenu
			;;

			5)
				echo "Restart services"
				sudo systemctl restart omnipy-rest.service
				sudo systemctl restart omnipy-beacon.service
				sudo systemctl restart omnipy-pan.service


				Services_Status=

                                if $(systemctl -q is-active omnipy-rest.service)
                                then
                                        Services_Status="Success: Omnipy Service has been restarted successfully\n"
                                else
                                        Services_Status="Failed: Omnipy Service has been not been restarted successfully\n"
                                fi


                                if $(systemctl -q is-active omnipy-beacon.service)
                                then
                                        Services_Status+="Success: Omnipy-beacon Service has been restarted successfully\n"
                                else
                                        Services_Status+="Failed: Omnipy-beacon Service has not been restarted successfully\n"
                                fi


                                if $(systemctl -q is-active omnipy-pan.service)
                                then
                                        Services_Status+="Success: Omnipy-pan Service has been restarted successfully"
                                else
                                        Services_Status+="Failed: Omnipy-pan Service has not been  restarted successfully"
                                fi

                                whiptail --title "Omnipy Services Restart " --msgbox "$Services_Status" 10 80
				DeveloperMenu
			;;

			6)
				echo "Verify RileyLink"
				python3 ~/omnipy/verify_rl.py
				DeveloperMenu
			;;
			7)
				echo "Configure Bluetooth"
				ConfigureBT
				DeveloperMenu

			;;
			8)
				echo "Reset REST-API password"
				/usr/bin/python3 /home/pi/omnipy/set_api_password.py
				DeveloperMenu

			;;


			9)
				DoBackup

			;;


			10)
				echo "Restore Omnipy backup - to be done"
				cd ~
				ListofBackups=`for x in $(ls -1 *.gz); do echo $x "-"; done`

				if [ -z "$ListofBackups" ]
				then
					whiptail --title "Restore Backup"  --msgbox "There are no backup to restore" 20 80
					DeveloperMenu

				else
					OPTION=$(whiptail --title "Restore backup"  --menu "Select the backup you want to restore:" 20 80 10 $ListofBackups  3>&1 1>&2 2>&3)
					exitstatus=$?
					if [ $exitstatus -ne 0 ]; then exit; fi;

					cd ~
					mv omnipy omnipy_revert	
					tar -xvzf $OPTION

					whiptail --title "Restore Backup" --msgbox "Your pi will now reboot, please reconnect in a minute..." 20 80
	                                sudo reboot
				fi
			;;

			11)
				Linetoadd="ForceCommand ./omnipy/scripts/console-ui.sh"
                                Filetochange="/etc/ssh/sshd_config"

				if (whiptail --title "Menu autostart?" --yesno "Do you want menu to be loaded at logon ?" 10 60) then
					#Check if the ForceCommand exists and if not, modify /etc/ssh/sshd_config file by adding ForceCommand ./Scripts/console-ui.sh

					if grep -Fxq "$Linetoadd" $Filetochange
						then
							# code if found
							echo "Already activated"
						else
							# code if not found
							echo "Line added"
							sudo sh -c "echo $Linetoadd >> $Filetochange"
							sudo systemctl restart ssh
					fi
				else
					#check if ForceCommand .$OMNIPY_HOME/scripts/console-ui.sh exits in /etc/ssh/sshd_config and it yes, remove it

					if grep -Fxq "$Linetoadd" $Filetochange
                                                then
                                                        # code if found
                                                        echo "Delete the line"
							sudo sed -i "\#$Linetoadd#d" "$Filetochange"
							sudo systemctl restart ssh
                                                else
                                                        # code if not found
                                                        echo "Already deactivated"
                                        fi
				fi
				DeveloperMenu
			;;


		esac


}

function MainMenu(){

while true
do

#check if Menu autostart is enabled
ExitbuttonName="Back to Shell"
AutoMenuCommand="ForceCommand ./Scripts/console-ui.sh"
sshdpath="/etc/ssh/sshd_config"

if grep -Fxq "$AutoMenuCommand" $sshdpath
	then
        	# code if found
                ExitbuttonName="Exit"
        else
                # code if not found
        	ExitbuttonName="Back to Shell"
fi

OPTION=$(whiptail --title "Omnipy Menu" --menu "Choose the action you want to perform" --cancel-button "$ExitbuttonName" 20 50 8  \
"1" "Activate New Pod" \
"2" "Deactivate Pod" \
"3" "Configure Raspberry Pi" \
"4" "Update Omnipy" \
"5" "Safe Reboot" \
"6" "Safe Shutdown" \
"7" "Escape to Shell" \
"8" "Advanced Settings" 3>&1 1>&2 2>&3)

exitstatus=$?
if [ $exitstatus -ne 0 ]; then exit; fi;

case $OPTION in

	1) #Activate a new pod
		NewPODActivation
	;;
	
	2)
		PODDeactivation
		MainMenu

	;;
	

	3)
		ConfigureRPi

	;;

	4)
		echo "Update Omnipy"
                if(whiptail --title "Update Omnipy" --yesno "Do you want to update omnipy to the latest master branch ?" 8 45)
                        then
                                UpdateOmnipy
                        else
                                echo "Omnipy update cancelled"
                fi

	;;

	5)
		echo "Safe Reboot"
                if(whiptail --title "Safe Reboot" --yesno "Do you want to reboot your pi ? If yes, you'll need to reconnect..." 8 45)
                        then
                                sudo reboot
                        else
                                echo "Reboot cancelled"
                fi

	;;

	6)
		echo "Safe Shutdown"
                if(whiptail --title "Safe Shutdown" --yesno "Do you want to shutdown your pi ? If yes, to restart the pi, unplug and plug again the power supply..." 8 45)
                        then
                                sudo shutdown now
                        else
                                echo "Shutdown cancelled"
                fi
	;;


	7) 
		echo "Escape to Shell"
                if(whiptail --title "Escape to Shell" --yesno "Type exit to return to the menu" 8 45)
                        then
                                bash
                        else
                                MainMenu
                fi
	;;

	8)
        DeveloperMenu
	
	;;

esac

done
}

MainMenu
