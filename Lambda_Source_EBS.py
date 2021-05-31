import boto3
import datetime
import base64
#create session and client
ec2_cli=boto3.client('ec2')
volume_list=["vol-02505de4105687e8e","vol-057a1a83a56d49280"]
src_accountId="255926189050"
dest_accountId="569907070050"
list_of_snaps = []
def lambda_handler(event, context):
    #######Delete old snapshot function#######
    def delete_old_snapshot():
        try:
            for snapshot in ec2_cli.describe_snapshots(OwnerIds=[src_accountId])['Snapshots']:
                snapshot_volume = snapshot['VolumeId']
               # mnt_vol = volume
                if 'Created by lambda function for raid disks' == snapshot['Description'] and (volume_list[0] == snapshot_volume or volume_list[1] == snapshot_volume):
                #print(snapshot['SnapshotId'])
                    snap_del_response = ec2_cli.delete_snapshot(SnapshotId=snapshot['SnapshotId'])
                    if snap_del_response['ResponseMetadata']['HTTPStatusCode'] == 200:
                        print('***Success!! Old snapshot:', snapshot['SnapshotId'], 'deleted')
        except Exception as e:
            print('***Error - Failed to delete old snapshot:', snapshot['SnapshotId'])
            print(type(e), ':', e)

    #######create snapshot function#######
    def create_snapshot():
        for volume in volume_list:
            try:
                #print (volume)
                response = ec2_cli.create_snapshot(
                    Description='Created by lambda function for raid disks',
                    VolumeId = volume,
                    TagSpecifications=[
                        {
                            'ResourceType': 'snapshot',
                            'Tags': [
                                {
                                    'Key': 'Name',
                                    'Value': 'WFS-snapshot-raid-disks'
                                },
                            ]
                        },
                    ],
                )
                if response['ResponseMetadata']['HTTPStatusCode'] == 200:
                    list_of_snaps.append(response['SnapshotId'])
                    print('***Success!! Creating snapshot:' , response['SnapshotId'], 'for volume:', volume)
            except Exception as e:
                print('***Error - Failed to creating snapshot of volume:', volume)
                print(type(e), ':', e)
        print("***Snapshot List Ids: ", list_of_snaps)
        
        ###Sharing snapshot with cross account####
        if len(list_of_snaps) == 2:
            snapshot_complete_waiter = ec2_cli.get_waiter('snapshot_completed')
            try:
                for snapshotId in list_of_snaps:
                    snapshot_complete_waiter.wait(SnapshotIds=[snapshotId])
                    SnapShare = ec2_cli.modify_snapshot_attribute(
                        Attribute='createVolumePermission',
                        OperationType='add',
                        SnapshotId=snapshotId,
                        UserIds=[dest_accountId, ],
                    )
                    print('***Success!! snapshot:', snapshotId, 'completed')
            except Exception as f:
                if "Max attempts exceeded" in f.message:
                    print('***Error Snapshot did not complete in 600 seconds.')
                else:
                    print(type(f), ':', f)
    
    print('Job start time',datetime.datetime.now())
    ###Call delete snapshot function####
    delete_old_snapshot()
    ###Call create snapshot function####
    create_snapshot()
    print('Job end time',datetime.datetime.now())

    ###############Invoke target account lambda function##################################
    def invokelambda():
        try:
            sts_connection = boto3.client('sts')
            acct_b = sts_connection.assume_role(
                RoleArn="arn:aws:iam::232974127418:role/Invoke_lambda_role",
                RoleSessionName="cross_acct_lambda")
            # print(acct_b)
            ACCESS_KEY = acct_b['Credentials']['AccessKeyId']
            SECRET_KEY = acct_b['Credentials']['SecretAccessKey']
            SESSION_TOKEN = acct_b['Credentials']['SessionToken']

            client = boto3.client('lambda',
                                   aws_access_key_id=ACCESS_KEY,
                                   aws_secret_access_key=SECRET_KEY,
                                   aws_session_token=SESSION_TOKEN,
                                   )

            response = client.invoke(
                FunctionName='arn:aws:lambda:ap-south-1:232974127418:function:raid_ebs_function',
                InvocationType='RequestResponse',
                LogType='Tail'
            )
            print('***success!! - Invoke target account lambda function')
            return response['LogResult']
        except Exception as e:
            print('***Error!! - Failed to invoke target account lambda function')
            print(type(e), ':', e)
            return 'error'
        
    #####Call function to invoke lambda frunction cross account####
    if list_of_snaps:
        target_log = invokelambda()
        lambda_res = base64.b64decode(target_log)
        print(lambda_res.decode('UTF-8'))