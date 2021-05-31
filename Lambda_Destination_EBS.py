import boto3
import datetime
ec2_cli=boto3.client(service_name="ec2",region_name="us-east-1")
volume_list=["vol-02505de4105687e8e","vol-057a1a83a56d49280"]
vol_map=["/dev/sdf","/dev/sdg"]
avai_Zone='us-east-1a'
accountId='255926189050'
Instance_Id = 'i-0a9cabbc807c67f92'
snapshot_list = []
list_new_vol = []
list_old_vol = []

def lambda_handler(event, context):
    ####Function for get instance status ##########
    def get_instance_state(Instance_Id):
        response = ec2_cli.describe_instances(InstanceIds=[Instance_Id])
        return response['Reservations'][0]['Instances'][0]['State']['Name']

    ####Function for instance power on or off ##########
    def instance_on_off(Instance_Id,status):
        try:
            if status == 'on':
                if 'running' == get_instance_state(Instance_Id):
                    print('***Warning!! instance :', Instance_Id, ' already running' )
                else:
                    ionstatus = ec2_cli.start_instances(InstanceIds=[Instance_Id])
                    if ionstatus['ResponseMetadata']['HTTPStatusCode'] == 200:
                        print('***Success!! instance :', Instance_Id, ' is going to start')
            elif status == 'off':
                if 'stopped' == get_instance_state(Instance_Id):
                    print('***Warning!! instance :', Instance_Id, ' already stopped')
                else:
                    ioffstatus = ec2_cli.stop_instances(InstanceIds=[Instance_Id])
                    if ioffstatus['ResponseMetadata']['HTTPStatusCode'] == 200:
                        print('***Success!! instance :', Instance_Id, ' is going to stop')
            else:
                print("invaild input")
        except Exception as e:
            print('***Error - Failed to instance: ', Instance_Id, status)
            print(type(e), ':', e)

    ####Function for get latest snapshot ##########
    def find_snapshots(volume):
        list_of_snaps = []
        for snapshot in ec2_cli.describe_snapshots(OwnerIds=[accountId])['Snapshots']:
            snapshot_volume = snapshot['VolumeId']
            mnt_vol = volume
            if mnt_vol == snapshot_volume:
                list_of_snaps.append({'date':snapshot['StartTime'], 'snap_id': snapshot['SnapshotId']})
            # sort snapshots order by date
        newlist = sorted(list_of_snaps, key=lambda k: k['date'], reverse=True)
        latest_snap_id = newlist[0]['snap_id']
        # The latest_snap_id provides the exact output snapshot ID
        snapshot_list.append(latest_snap_id)
        return latest_snap_id

    ####Function for creat volume ##########
    def create_volume_from_snapshot():
        i = 0
        for volume in volume_list:
            i = i + 1
            try:
                #print ('loop-'+ str(i))
                response = ec2_cli.create_volume(
                    AvailabilityZone=avai_Zone,
                    Encrypted=False,
                    SnapshotId=find_snapshots(volume),
                    VolumeType='gp2',
                    TagSpecifications = [
                                        {
                                            'ResourceType': 'volume',
                                            'Tags': [{'Key': 'Name','Value': ('raid_disk-' + str(i))},]
                                        },
                                    ],
                )
                if response['ResponseMetadata']['HTTPStatusCode'] == 200:
                    volume_id = response['VolumeId']
                    list_new_vol.append(volume_id)
                    print('***Success!! New volume:', volume_id, 'is creating...')
            except Exception as e:
                print('***Error - Failed to creating new volume.')
                print(type(e), ':', e)
    
    ####Function for get volume status ##########
    def get_volume_status(new_vol):
        response = ec2_cli.describe_volumes(VolumeIds=[new_vol])
        return response['Volumes'][0]['State']

    ####Function for get old volume Id#########
    def get_old_volume_id(Instance_Id,device):
        response = ec2_cli.describe_volumes(Filters=[{'Name': 'attachment.device', 'Values': [device]},
                                                     {'Name': 'attachment.instance-id',
                                                      'Values': [Instance_Id]},
                                                     {'Name': 'status', 'Values': ['in-use']}])
        if len(response['Volumes']) == 0:
            return "No_volume_found"
        else:
            return response['Volumes'][0]['VolumeId']

    ####Function for volume detach and attach ##########
    def volume_detach_attach(vol_map,list_new_vol,Instance_Id):
       try:
            ####Check instance status before detach volume######
            if 'stopped' != get_instance_state(Instance_Id):
                instance_stop_waiter = ec2_cli.get_waiter('instance_stopped')
                instance_stop_waiter.wait(InstanceIds=[Instance_Id])
                print('***Success!! instance :', Instance_Id, ' is stopped')
            else:
                print('***Success!! instance :', Instance_Id, ' is stopped')

            print (list_new_vol)
            #######Check new volume status before detach old volume####
            for new_vol in list_new_vol:
                if 'available' == get_volume_status(new_vol):
                    print('***Success!! New-volume:', new_vol, 'is created')
                else:
                    volume_create_waiter = ec2_cli.get_waiter('volume_available')
                    volume_create_waiter.wait(VolumeIds=[new_vol])
                    print('***Success!! New-volume:', new_vol, 'is created')
            
            #######Detach old volume#####
            for x in range(0, 2):
                oldvolume_id=get_old_volume_id(Instance_Id,device=vol_map[x])
                if oldvolume_id != 'No_volume_found':
                    detach_response = ec2_cli.detach_volume(
                        Device=vol_map[x],
                        InstanceId=Instance_Id,
                        VolumeId=oldvolume_id,
                    )
                    if detach_response['ResponseMetadata']['HTTPStatusCode'] == 200:
                        print('***Success!! old-volume:', oldvolume_id, 'is detaching from instance: ', Instance_Id)
                        list_old_vol.append(oldvolume_id)

            if len(list_old_vol) != 0:
                for old_vol in list_old_vol:
                    if 'available' == get_volume_status(old_vol):
                        print('***Success!! old-volume:', old_vol, 'is detached from instance: ', Instance_Id)
                    else:
                        volume_detach_waiter = ec2_cli.get_waiter('volume_available')
                        volume_detach_waiter.wait(VolumeIds=[old_vol])
                        print('***Success!! old-volume:', old_vol, 'is detached from instance: ', Instance_Id)
            
            ######Attach new volume######
            for y in range(0, 2):
                atachresponse = ec2_cli.attach_volume(
                    Device=vol_map[y],
                    InstanceId=Instance_Id,
                    VolumeId=list_new_vol[y]
                )
                if atachresponse['ResponseMetadata']['HTTPStatusCode'] == 200:
                    print('***Success!! New volume:', list_new_vol[y], 'is attaching with instance:', Instance_Id)

            for new_volume in list_new_vol:
                if 'in-use' == get_volume_status(new_volume):
                    print('***Success!! New-volume:', new_volume, 'is attached')
                else:
                    volume_create_waiter = ec2_cli.get_waiter('volume_in_use')
                    volume_create_waiter.wait(VolumeIds=[new_volume])
                    print('***Success!! New-volume:', new_volume, 'is attached')
            return "success"
       except Exception as e:
           print('***Error - Failed to volume detach and attach.')
           print(type(e), ':', e)
           return "failed"

    ####Function for old volume delete ##########
    def old_volume_delete(list_old_vol):
        if len(list_old_vol) != 0:
            for vol in list_old_vol:
                removeresponse = ec2_cli.delete_volume(VolumeId=vol)
                if removeresponse['ResponseMetadata']['HTTPStatusCode'] == 200:
                    print('***Success!! old volume:', vol, 'is deleted')

    print('Job start time',datetime.datetime.now())
    ###call instance power off function####
    instance_on_off(Instance_Id,status='off')
    ###call function for volume creation####
    create_volume_from_snapshot()
    if len(list_new_vol) != 0:
        ###call function for detach and attache volume#####
        if 'success' == volume_detach_attach(vol_map,list_new_vol,Instance_Id):
            ###call function for delete old volume#####
            old_volume_delete(list_old_vol)
    ###call function for instance power on####
    instance_on_off(Instance_Id,status='on')
    print('Job end time',datetime.datetime.now())
