import os
import sys
sys.path.append('.')

import numpy as np
import joblib
import torch
import os
import joblib
import argparse
import numpy as np
import json
import smplx
import glob
import math
from loguru import logger
from tqdm import tqdm
import os.path as osp
from teach.transforms.smpl import get_body_model

AMASS_DIRS = [
    'ACCAD/ACCAD', # 19 mins
    'BMLrub/BioMotionLab_NTroje', # 5:40 hours
    'CMU/CMU', # 5:38 h
    'BMLmovi/BMLmovi', # 2:20h
    'EKUT/EKUT', # 19 mins
    'DFaust67/DFaust_67', # 7'
    'HumanEva/HumanEva', # 5'
    'EyesJapanDataset/Eyes_Japan_Dataset', # 4hours
    'KIT/KIT', # ~8h
    'MPIHDM05/MPI_HDM05', # 1:51
    'MPILimits/MPI_Limits', # 5'
    'MPImosh/MPI_mosh', # 10'
    'SFU/SFU', # 8'
    'SSMsynced/SSM_synced', #2'
    'TCDhandMocap/TCD_handMocap', # 3'
    'TotalCapture/TotalCapture', # 20'
    'Transitionsmocap/Transitions_mocap', # 20'
    'TCDhandMocap/TCD_handMocap',
    'DanceDB/DanceDB',
    'BMLhandball/BMLhandball']

OUT_FPS = 30
DISCARD_SHORTER_THAN = 0.5 # seconds
# extract SMPL joints from SMPL-H model
joints_to_use = np.array([
    0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10,
    11, 12, 13, 14, 15, 16, 17, 18, 19,
    20, 21, 22, 37])
JOINT_SMPLH2SMPL = np.arange(0,156).reshape((-1,3))[joints_to_use].reshape(-1)

'''
EXAMPLE USAGE:

python divotion/dataset/process_amass.py --input-path /ps/scratch/ps_shared/nathanasiou/data/amass_smplx
                                         --output-path /ps/scratch/ps_shared/nathanasiou/data/processed_amass_smplx_neutral_wshape
                                         --model-type smplx --use-betas

'''

def param_dict_for_body_model(pose_vector, trans, betas=None, model_type='smpl'):

    body_params = {}

    assert pose_vector.shape[0] == trans.shape[0]
    seqlen = pose_vector.shape[0]

    if betas is None:
        betas = torch.from_numpy(np.zeros(10)).unsqueeze(0).repeat(seqlen, 1).float().cuda()
    else:
        betas = torch.from_numpy(betas[:10]).unsqueeze(0).repeat(seqlen, 1).float().cuda()

    if model_type.split('_')[0] == 'smplx':
        body_params['global_orient'] = torch.from_numpy(pose_vector[:, :3]).float().cuda()
        body_params['body_pose'] = torch.from_numpy(pose_vector[:, 3:66]).float().cuda()
        body_params['jaw_pose']  = torch.from_numpy(pose_vector[:, 66:69]).float().cuda()
        body_params['leye_pose'] = torch.from_numpy(pose_vector[:, 69:72]).float().cuda()
        body_params['reye_pose'] = torch.from_numpy(pose_vector[:, 72:75]).float().cuda()
        body_params['left_hand_pose'] = torch.from_numpy(pose_vector[:, 75:120]).float().cuda()
        body_params['right_hand_pose'] = torch.from_numpy(pose_vector[:, 120:]).float().cuda()
        body_params['transl'] = torch.from_numpy(trans).float().cuda()
        body_params['betas'] = betas
    elif model_type.split('_')[0] == 'smplh':
        body_params['global_orient'] = torch.from_numpy(pose_vector[:, :3]).float().cuda()
        body_params['body_pose'] = torch.from_numpy(pose_vector[:, 3:66]).float().cuda()
        body_params['left_hand_pose'] = torch.from_numpy(pose_vector[:, 66:111]).float().cuda()
        body_params['right_hand_pose'] = torch.from_numpy(pose_vector[:, 111:]).float().cuda()
        body_params['transl'] = torch.from_numpy(trans).float().cuda()
        body_params['betas'] = betas
    elif model_type.split('_')[0] == 'smpl':
        body_params['global_orient'] = torch.from_numpy(pose_vector[:, :3]).float().cuda()
        body_params['body_pose'] = torch.from_numpy(pose_vector[:, 3:]).float().cuda()
        body_params['transl'] = torch.from_numpy(trans).float().cuda()
        body_params['betas'] = betas
    else:
        sys.exit(f'Unrecognized Body Model: {model_type}.')

    return body_params


def process_sequence(filename, body_model_type, marker_set, use_betas,
                     gender):
    
    f_id = '/'.join(filename.split('/')[-4:])
    # logger.info(f'Processing sequence: {f_id}..')
    # THIS IS AMASS BUG AND EVENTUALLY SHOULD BE REMOVED 
    try:
        amass_sequence_data = dict(np.load(filename, allow_pickle=True))
    except:
        logger.info(f'Could not load {filename}')
        return {}
    # THIS IS AMASS BUG AND EVENTUALLY SHOULD BE REMOVED 

    if model_type == 'smplx':
        sequence_fps = amass_sequence_data['mocap_frame_rate']
    elif model_type in ['smplh', 'smpl']:
        sequence_fps = amass_sequence_data['mocap_framerate']

    # correct mislabeled data
    if filename.find('BMLhandball') >= 0:
        sequence_fps = 240
    if filename.find('20160930_50032') >= 0 or \
        filename.find('20161014_50033') >= 0:
        sequence_fps = 59

    num_frames = amass_sequence_data['poses'].shape[0]

    # discard sequence if it shorter than treshold seconds
    if num_frames < DISCARD_SHORTER_THAN*sequence_fps:
        return {}

    if OUT_FPS > sequence_fps:
        print('Cannot supersample data, saving at data rate!')
    else:
        fps_ratio = float(OUT_FPS) / sequence_fps
        new_num_frames = int(fps_ratio*num_frames)
        # print(cur_num_frames)
        # print(new_num_frames)
        downsample_ids = np.linspace(0, num_frames-1,
                                        num=new_num_frames, dtype=int)
    if model_type == 'smplx':
        pose_feats = ['trans', 'poses', 'root_orient', 'pose_body',
                      'pose_hand', 'pose_jaw', 'pose_eye']

    elif model_type in ['smplh', 'smpl']:
        pose_feats = ['trans', 'poses']

    for k, v in amass_sequence_data.items():
        if k in pose_feats:
            amass_sequence_data[k] = v[downsample_ids]
    final_seq_data = {}

    if model_type == 'smplx':
        final_seq_data['poses'] = amass_sequence_data['poses']
    elif model_type == 'smpl':
        final_seq_data['poses'] = amass_sequence_data['poses'][:, JOINT_SMPLH2SMPL]
    elif model_type == 'smplh':
        final_seq_data['poses'] = amass_sequence_data['poses']
    gender_of_seq = amass_sequence_data['gender']
    if 'SSM_synced' in filename:
        gender_of_seq = np.array(amass_sequence_data['gender'], ndmin=1)[0]

    gender_of_seq = str(gender_of_seq, 'utf-8') \
             if isinstance(gender_of_seq, bytes) \
             else str(gender_of_seq)

    final_seq_data['trans'] = amass_sequence_data['trans']
    final_seq_data['fps'] = OUT_FPS
    final_seq_data['fname'] = f_id
    if gender != 'amass':
        body_model_type = f'{body_model_type}_{gender}'
    if use_betas:
        final_seq_data['betas'] = amass_sequence_data['betas']
        body_params = param_dict_for_body_model(final_seq_data['poses'], 
                                                final_seq_data['trans'],
                                                betas=final_seq_data['betas'],
                                                model_type=body_model_type)
    else:
        body_params = param_dict_for_body_model(final_seq_data['poses'],
                                                final_seq_data['trans'],
                                                model_type=body_model_type)
    # must do SMPL forward pass to get joints
    # workaround to avoid running out of GPU
    body_joint_chunk = []
    body_marker_chunk = []
    slice_ids = [0, min([new_num_frames, 1500])]
    while slice_ids[0] < new_num_frames:

        sidx, eidx = slice_ids
        body_params_temp = {}
        for k, v in body_params.items():
            body_params_temp[k] = v[sidx:eidx]
        bodymodel_seq = get_body_model(model_type, 
                                       gender_of_seq if gender=='amass' else gender,
                                       eidx-sidx, device='cuda')

        smplx_output = bodymodel_seq(return_verts=True, **body_params_temp)
        # extract joints and markers

        joints_temp = smplx_output.joints.detach().cpu().numpy()

        if model_type == 'smpl':
            joints_temp = smplx_output.joints[:, :22].detach().cpu().numpy()

        markers_ssm_temp = smplx_output.vertices[:, marker_set, :].detach().cpu().numpy()

        body_joint_chunk.append(joints_temp)
        body_marker_chunk.append(markers_ssm_temp)

        slice_ids[0] = slice_ids[1]
        slice_ids[1] = min([new_num_frames, slice_ids[1] + 1000])

    joint_pos = np.concatenate(body_joint_chunk, axis=0)
    markers_ssm = np.concatenate(body_marker_chunk, axis=0)

    final_seq_data['joint_positions'] = joint_pos
    final_seq_data['markers'] = markers_ssm

    return final_seq_data


def read_data(input_dir, model_type, output_dir, use_betas, gender):
    if model_type in ['smplh', 'smpl']:
        amass_subsets = [f'{input_dir}/{x}' for x in AMASS_DIRS
                        if os.path.isdir(f'{input_dir}/{x}')]

        with open('data/smpl_models/markers_mosh/smplh/SSM67.json') as f:
            marker_ssm67 = list(
                json.load(f)['markersets'][0]['indices'].values())

    elif model_type=='smplx':
        amass_subsets = glob.glob(f'{input_dir}/*')

        with open('data/smpl_models/markers_mosh/smplx/SSM2.json') as f:
            marker_ssm67 = list(
                json.load(f)['markersets'][0]['indices'].values())
    else:
        sys.exit('Invalid model type')
    all_data = []
    for sset in amass_subsets:
        seqs = glob.glob(f'{sset}/*/*.npz')
        dataset_name = sset.strip().split('/')[-1]
        logger.info('-- processing subset {:s}'.format(dataset_name))
        dataset_db_list = []
        out_dir = f'{output_dir}/{dataset_name}'
        if  os.path.isdir(out_dir) and any(os.scandir(out_dir)):
            logger.info(f'The directory: {out_dir}/{dataset_name} '\
                         'is not empty, so continuing to the next dataset..')
            continue
        # main loop to process each sequence
        for seq in tqdm(seqs):
            # read data
            if os.path.basename(seq) == 'neutral_stagei.npz' or \
                os.path.basename(seq) == 'shape.npz':
                continue
            final_seq_data = process_sequence(seq, model_type, marker_ssm67, 
                                              use_betas, gender)
            if final_seq_data:
                dataset_db_list.append(final_seq_data)
        os.makedirs(out_dir, exist_ok=True)

        dataset_db_fname = f'{out_dir}/{dataset_name}.pth.tar'
        no_segs = len(dataset_db_list)
        logger.info(f'Finished {dataset_name} resulting in {no_segs} sequences..')
        logger.info(f'Saving {dataset_name} dataset to {dataset_db_fname}...')
        joblib.dump(dataset_db_list, dataset_db_fname)
        all_data.extend(dataset_db_list)
 
    joblib.dump(all_data, f'{output_dir}/amass.pth.tar')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    parser.add_argument('--input-path', required=True, type=str,
                        help='input path of AMASS data in unzipped format without anything else.')
    parser.add_argument('--output-path', required=True, type=str, 
                        help='output path of AMASS data in unzipped format without anything else.')
    parser.add_argument('--model-type', type=str, required=True,
                        help='SMPL/SMPLH or SMPLX')
    parser.add_argument('--use-betas', default=False, action='store_true',
                        help='creates submission files for cluster')
    parser.add_argument('--gender', required=True, choices=['male', 'female', 
                                                          'neutral', 'amass'],
                        type=str, help='hard-code the gender or use amass gender')


    args = parser.parse_args()
    input_dir = args.input_path
    output_dir = args.output_path
    model_type = args.model_type
    use_betas = args.use_betas
    gender = args.gender

    logger.info(f'Input arguments: \n {args}')

    db = read_data(input_dir, model_type, output_dir, use_betas, gender)