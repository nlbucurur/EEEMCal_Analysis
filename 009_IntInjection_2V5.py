import packetlib, caliblib
import socket, json, time, os, sys, uuid, copy, csv
import numpy as np
from matplotlib import pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from tqdm import tqdm
from loguru import logger
import argparse
from caliblib import decompress_tot

script_id_str       = os.path.basename(__file__).split('.')[0]
script_version_str  = '1.0'

# Remove the default logger configuration
logger.remove()

class TqdmSink:
    def __init__(self):
        self.level = "DEBUG"

    def write(self, message):
        tqdm.write(message.rstrip())  # Remove the trailing newline

# Add the custom tqdm sink with colored formatting for different levels
logger.add(
    TqdmSink(), 
    format="<green>{time:HH:mm:ss}</green> - "
           "<level>{level: <8}</level> - "
           "<level>{message}</level>",
    level="DEBUG",
    colorize=True,
    backtrace=True,
    diagnose=True,
)

# * --- Read command line arguments -----------------------------------------------------
# * -------------------------------------------------------------------------------------
parser = argparse.ArgumentParser(description='Internal Injection')
parser.add_argument('-c', '--config', type=str, help='Path to the common settings JSON file')
parser.add_argument('-i', '--i2c', type=str, nargs='+', help='Paths to the I2C settings JSON files')
parser.add_argument('-o', '--output', type=str, help='Output folder name')
args = parser.parse_args()

if args.config is not None:
    print(f"Common settings file: {args.config}")
if args.i2c is not None:
    print(f"I2C settings files: {args.i2c}")
if args.output is not None:
    print(f"Output folder: {args.output}")

# -- Handle input config json files--------------------------------------------
# -----------------------------------------------------------------------------
input_i2c_json_names = []
input_i2c_json_name_default = 'config/default_2024Aug_config.json'

if args.i2c is not None:
    # if there is space in between the path, there are two files
    # make sure it is string, not list
    i2c_string = ''
    if isinstance(args.i2c, list):
        i2c_string = args.i2c[0]
    else:
        i2c_string = args.i2c
        
    if ',' in i2c_string:
        i2c_file_names = i2c_string.split(',')
        if len(i2c_file_names) != 2:
            logger.error("Invalid I2C settings file")
            sys.exit(1)
        for i2c_file_name in i2c_file_names:
            if not i2c_file_name.endswith('.json'):
                logger.error("I2C settings file must be in JSON format")
                sys.exit(1)
            input_i2c_json_names.append(i2c_file_name)
    else:
        if os.path.exists(i2c_string):
            if not i2c_string.endswith('.json'):
                logger.error("I2C settings file must be in JSON format")
                sys.exit(1)
            input_i2c_json_names.append(i2c_string)
        else:
            logger.error(f"I2C settings file {i2c_string} does not exist")
            sys.exit(1)
else:
    input_i2c_json_names.append(input_i2c_json_name_default)
# -----------------------------------------------------------------------------

# * --- Load udp pool configuration file ------------------------------------------------
# * -------------------------------------------------------------------------------------
cfg_path = os.path.join(os.path.dirname(__file__), 'config/socket_pool_config.json')
with open(cfg_path, 'r') as f:
    cfg = json.load(f)

CONTROL_HOST = cfg['CONTROL_HOST']
CONTROL_PORT = cfg['CONTROL_PORT']
DATA_HOST    = cfg['DATA_HOST']
DATA_PORT    = cfg['DATA_PORT']
BUFFER_SIZE  = cfg['BUFFER_SIZE']

# * --- Set up output folder and config file --------------------------------------------
# * -------------------------------------------------------------------------------------
outputs            = caliblib.setup_output(script_id_str, args.output)
output_dump_folder = outputs['dump_folder']
output_config_path = outputs['config_path']
output_pedecalib_json_name = outputs['pedecalib_name']
output_config_json = outputs['config_json']
output_folder_name = outputs['output_folder']
output_config_json_name = outputs['output_config_json']
pdf_file           = outputs['pdf_file']

# -- Find UDP settings --------------------------------------------------------
# -----------------------------------------------------------------------------
common_settings_json_path = "config/common_settings_3B.json"
if args.config is not None:
    if os.path.exists(args.config):
        if not args.config.endswith('.json'):
            logger.error("Common settings file must be in JSON format")
            sys.exit(1)
        common_settings_json_path = args.config
    else:
        logger.error(f"Common settings file {args.config} does not exist")
        sys.exit(1)

is_common_settings_exist  = False
try:
    with open(common_settings_json_path, 'r') as json_file:
        common_settings_json = json.load(json_file)
        is_common_settings_exist = True
except:
    logger.warning(f"Common settings file {common_settings_json_path} does not exist")
# -----------------------------------------------------------------------------

# -- Register values ----------------------------------------------------------
# -----------------------------------------------------------------------------
i2c_settings_json_path = "config/h2gcroc_1v4_r1.json"
reg_settings = packetlib.RegisterSettings(i2c_settings_json_path)
i2c_config = json.load(open(i2c_settings_json_path, 'r'))

i2c_dict = {}
for key in list(i2c_config['I2C_address'].keys()):
   i2c_dict[key] = i2c_config['I2C_address'][key]
# -----------------------------------------------------------------------------

# -- Default UDP settings -----------------------------------------------------
# -----------------------------------------------------------------------------
h2gcroc_ip      = "10.1.2.208"
pc_ip           = "10.1.2.207"
h2gcroc_port    = 11000
pc_cmd_port     = 11000
pc_data_port    = 11001
timeout         = 1 # seconds

if is_common_settings_exist:
    try:
        udp_settings    = common_settings_json['udp']
        h2gcroc_ip      = udp_settings['h2gcroc_ip']
        pc_ip           = udp_settings['pc_ip']
        h2gcroc_port    = udp_settings['h2gcroc_port']
        pc_data_port    = udp_settings['pc_data_port']
        pc_cmd_port     = udp_settings['pc_cmd_port']
    except:
        logger.warning("Failed to load common settings")
        is_common_settings_exist = False

logger.info(f"UDP settings: H2GCROC IP: {h2gcroc_ip}, PC IP: {pc_ip}, H2GCROC Port: {h2gcroc_port}")
logger.info(f"PC Data Port: {pc_data_port}, PC Command Port: {pc_cmd_port}")

fpga_address    = int(h2gcroc_ip.split('.')[-1]) - 208
worker_id       = str(uuid.uuid4())

try:
    ctrl_conn, data_cmd_conn, data_data_conn, cmd_outbound_conn, pool_do = caliblib.init_worker_sockets(
        worker_id, h2gcroc_ip, pc_ip,
        CONTROL_HOST, CONTROL_PORT, DATA_HOST, DATA_PORT,
        pc_cmd_port, pc_data_port,
        timeout, logger
    )
except Exception as e:
    logger.critical(f"Failed to initialize worker sockets: {e}")
    logger.critical("Please check the socket pool server and try again.")
    exit()

pool_do("register",   "data", pc_data_port)
pool_do("register",   "cmd",  pc_cmd_port)

output_pedecalib_json = {}  # output json for pedestal calibration

output_pedecalib_json['udp'] = {
    'h2gcroc_ip': h2gcroc_ip,
    'pc_ip': pc_ip,
    'h2gcroc_port': h2gcroc_port,
    'pc_data_port': pc_data_port,
    'pc_cmd_port': pc_cmd_port,
    'timeout': timeout
}
# -----------------------------------------------------------------------------

# -- DAQ settings -------------------------------------------------------------
# -----------------------------------------------------------------------------
total_asic              = 2

# - i2c_retry: number of retries for i2c communication
# - (DNU) i2c_fragment_life: number of fragments to wait for a complete event
i2c_retry               = 50
i2c_fragment_life       = 3

# - machine_gun: number of samples to take for every cycle, recommend to keep under 20,
#                0 means 1 sample per cycle
# - phase_setting: phase setting for the ASIC clock (0 - 15)
machine_gun             = 10
phase_setting           = 12

# - gen_nr_cycle: number of cycles to run the generator
# - (DNU) gen_interval_value: interval value for the generator
gen_nr_cycle            = 1
gen_interval_value      = 1000
expected_event_number   = gen_nr_cycle * (machine_gun + 1)
gen_pre_interval_value  = 15

# - (DNU) gen_fcmd_internal_injection: fast command for internal injection
# - (DNU) gen_fcmd_L1A: fast command for L1A request
gen_fcmd_internal_injection = 0b00101101
gen_fcmd_L1A                = 0b01001011

channel_not_used        = []
dead_channel_list       = []

# -- Read pedestal calibration settings ---------------------------------------
# -----------------------------------------------------------------------------
input_pede_jsons = []
input_pede_phase = []

if total_asic == len(input_i2c_json_names):
    for _input_i2c_json_name_index, _input_i2c_json_name in enumerate(input_i2c_json_names):
        if os.path.exists(_input_i2c_json_name):
            _input_json = json.load(open(_input_i2c_json_name))
            if _input_json["Target ASIC"]["ASIC Address"] == _input_i2c_json_name_index:
                input_pede_jsons.append(_input_json)
                _input_pede_json = _input_json
                if "PedestalCalib" in _input_pede_json:
                    if "phase_setting" in _input_pede_json["PedestalCalib"]:
                        input_pede_phase.append(_input_pede_json["PedestalCalib"]["phase_setting"])
                if "DeadChannels" in _input_pede_json["PedestalCalib"]:
                    for _dead_channel in _input_pede_json["PedestalCalib"]["DeadChannels"]:
                        dead_channel_list.append(_dead_channel)
                    dead_channel_list = list(set(dead_channel_list))
        else:
            logger.error(f"I2C settings file {_input_i2c_json_name} does not exist")
            sys.exit(1)
else:
    if len(input_i2c_json_names) == 1:
        # duplicate the same settings for all ASICs
        for _asic in range(total_asic):
            _input_json = json.load(open(input_i2c_json_names[0]))
            if _input_json["Target ASIC"]["ASIC Address"] == _asic:
                input_pede_jsons.append(_input_json)
                _input_pede_json = _input_json
                if "PedestalCalib" in _input_pede_json:
                    if "phase_setting" in _input_pede_json["PedestalCalib"]:
                        input_pede_phase.append(_input_pede_json["PedestalCalib"]["phase_setting"])
                if "DeadChannels" in _input_pede_json["PedestalCalib"]:
                    for _dead_channel in _input_pede_json["PedestalCalib"]["DeadChannels"]:
                        dead_channel_list.append(_dead_channel)
                    dead_channel_list = list(set(dead_channel_list))
    else:
        logger.error("Number of I2C settings files does not match the number of ASICs")
        sys.exit(1)

if len(set(input_pede_phase)) == 1:
    phase_setting = input_pede_phase[0]
    logger.info(f"Phase setting found in the input pedecalib files: {phase_setting}")
elif len(set(input_pede_phase)) > 1:
    logger.warning("Different phase settings are found in the input pedecalib files, using the default value")
else:
    logger.warning("No phase setting found in the input pedecalib files, using the default value")

logger.debug(f"Input I2C JSON names: {input_i2c_json_names}")
logger.debug(f"Input Pedestal Phase: {input_pede_phase}")
# -----------------------------------------------------------------------------

# * --- Scan Settings -------------------------------------------------------------------
# * -------------------------------------------------------------------------------------
phase_settings  = [0, 1, 2, 3, 5, 8, 9, 10, 11, 12, 13, 14, 15]
#phase_settings = [1]

scan_chn_pack   = 1
scan_start_chn  = 0
scan_chn_numbers_per_asic = 18   # how many channels to scan for each ASIC

dac_value       = 200

pedestal_subtraction = True
pedestal_setting = 80

# constant values
sample_time_interval = 25.0
phase_time_interval  = 25.0/16.0
phase_offset    = 7

# * --- Set up registers ----------------------------------------------------------------
# * -------------------------------------------------------------------------------------
scan_config = []

for _asic in range(total_asic):
    _asic_scan_config = {}
    _asic_config_json = input_pede_jsons[_asic]

    _asic_top_reg = _asic_config_json["Register Settings"]["Top                 "]
    _asic_top_reg = [int(x, 16) for x in _asic_top_reg.split()]

    _asic_top_reg_runLR     = _asic_top_reg.copy()
    _asic_top_reg_runLR[0]  = _asic_top_reg_runLR[0] | 0x03
    _asic_top_reg_runLR     = _asic_top_reg_runLR[:8]
    _asic_top_reg_runLR[7]  = phase_setting & 0x0F

    _asic_top_reg_offLR     = _asic_top_reg.copy()
    _asic_top_reg_offLR[0]  = _asic_top_reg_offLR[0] & 0xFC
    _asic_top_reg_offLR     = _asic_top_reg_offLR[:8]
    _asic_top_reg_offLR[7]  = phase_setting & 0x0F

    _asic_global_analog_0 = _asic_config_json["Register Settings"]["Global_Analog_0     "]
    _asic_global_analog_1 = _asic_config_json["Register Settings"]["Global_Analog_1     "]

    _asic_global_analog_0 = [int(x, 16) for x in _asic_global_analog_0.split()]
    _asic_global_analog_1 = [int(x, 16) for x in _asic_global_analog_1.split()]

    _asic_reference_voltage_0 = _asic_config_json["Register Settings"]["Reference_Voltage_0 "]
    _asic_reference_voltage_1 = _asic_config_json["Register Settings"]["Reference_Voltage_1 "]

    _asic_reference_voltage_0 = [int(x, 16) for x in _asic_reference_voltage_0.split()]
    _asic_reference_voltage_1 = [int(x, 16) for x in _asic_reference_voltage_1.split()]

    _asic_digital_half_0 = _asic_config_json["Register Settings"]["Digital_Half_0      "]
    _asic_digital_half_1 = _asic_config_json["Register Settings"]["Digital_Half_1      "]

    _asic_digital_half_0 = [int(x, 16) for x in _asic_digital_half_0.split()]
    _asic_digital_half_1 = [int(x, 16) for x in _asic_digital_half_1.split()]

    _asic_scan_config["top_reg_runLR"] = _asic_top_reg_runLR
    _asic_scan_config["top_reg_offLR"] = _asic_top_reg_offLR

    _asic_scan_config["ref_voltage_0"] = _asic_reference_voltage_0
    _asic_scan_config["ref_voltage_1"] = _asic_reference_voltage_1

    _asic_scan_config["global_analog_0"] = _asic_global_analog_0
    _asic_scan_config["global_analog_1"] = _asic_global_analog_1

    _asic_scan_config["digital_half_0"] = _asic_digital_half_0
    _asic_scan_config["digital_half_1"] = _asic_digital_half_1

    _asic_scan_config["top_reg_runLR"] = _asic_top_reg_runLR
    _asic_scan_config["top_reg_offLR"] = _asic_top_reg_offLR

    # _asic_scan_config["toa_global_threshold"] = [initial_toa_global_threshold for _ in range(2)]
    # _asic_scan_config["tot_global_threshold"] = [initial_tot_global_threshold for _ in range(2)]

    # _asic_scan_config["tot_chn_threshold"] = [initial_tot_threshold_trim for _ in range(76)]
    # _asic_scan_config["toa_chn_threshold"] = [initial_toa_threshold_trim for _ in range(76)]

    _asic_scan_config["config"] = _asic_config_json

    if "PedeCalib" in _asic_config_json:
        logger.info("Dead channels and not used channels are loaded from the config file")
        for _dead_channel in _asic_config_json["PedestalCalib"]["DeadChannels"]:
            dead_channel_list.append(_dead_channel)
        dead_channel_list = list(set(dead_channel_list))
        for _not_used_channel in _asic_config_json["PedestalCalib"]["ChannelNotUsed"]:
            channel_not_used.append(_not_used_channel)
        channel_not_used = list(set(channel_not_used))

    scan_config.append(_asic_scan_config)

try:
    for _asic in range(total_asic):
        _asic_config = scan_config[_asic]
        for _reg_key in _asic_config["config"]["Register Settings"]:
            if "Channel_" in _reg_key or "CM_" in _reg_key or "CALIB_" in _reg_key:
                _reg_val  = _asic_config["config"]["Register Settings"][_reg_key]
                _reg_val  = [int(x, 16) for x in _reg_val.split()]
                _reg_key_clear = _reg_key.replace(" ", "")
                if "Channel_" in _reg_key:
                    if int(_reg_key_clear.split("_")[1]) < 10:
                        _reg_key_clear = _reg_key_clear.replace("_", "_0")
                
                _reg_addr = i2c_dict[_reg_key_clear]

                if not packetlib.send_check_i2c_wrapper(cmd_outbound_conn, data_cmd_conn, h2gcroc_ip, h2gcroc_port, asic_num=_asic, fpga_addr = fpga_address, sub_addr=_reg_addr, reg_addr=0x00, data=_reg_val, retry=i2c_retry, verbose=False):
                    logger.warning(f"Failed to set Channel Wise Register {_reg_key} for ASIC {_asic}")

            elif "Global_Analog_" in _reg_key: 
                _reg_val  = _asic_config["config"]["Register Settings"][_reg_key]
                _reg_val  = [int(x, 16) for x in _reg_val.split()]
                _reg_val[8]  = 0xA0
                _reg_val[9]  = 0xCA
                _reg_val[10] = 0x42
                _reg_val[14] = 0x6F
                _reg_key_clear = _reg_key.replace(" ", "")
                _reg_addr = i2c_dict[_reg_key_clear]

                if not packetlib.send_check_i2c_wrapper(cmd_outbound_conn, data_cmd_conn, h2gcroc_ip, h2gcroc_port, asic_num=_asic, fpga_addr = fpga_address, sub_addr=_reg_addr, reg_addr=0x00, data=_reg_val, retry=i2c_retry, verbose=False):
                    logger.warning(f"Failed to set Global Analog Register {_reg_key} for ASIC {_asic}")

            elif "Digital_Half_" in _reg_key:
                _reg_val  = _asic_config["config"]["Register Settings"][_reg_key]
                _reg_val  = [int(x, 16) for x in _reg_val.split()]
                _reg_val[4]  = 0xC0
                _reg_val[25] = 0x02
                _reg_key_clear = _reg_key.replace(" ", "")
                _reg_addr = i2c_dict[_reg_key_clear]

                if not packetlib.send_check_i2c_wrapper(cmd_outbound_conn, data_cmd_conn, h2gcroc_ip, h2gcroc_port, asic_num=_asic, fpga_addr = fpga_address, sub_addr=_reg_addr, reg_addr=0x00, data=_reg_val, retry=i2c_retry, verbose=False):
                    logger.warning(f"Failed to set Digital Half Register {_reg_key} for ASIC {_asic}")

        # if not packetlib.send_check_i2c_wrapper(cmd_outbound_conn, data_cmd_conn, h2gcroc_ip, h2gcroc_port, asic_num=_asic, fpga_addr = fpga_address, sub_addr=packetlib.subblock_address_dict["Top"], reg_addr=0x00, data=_asic_config["top_reg_runLR"], retry=i2c_retry, verbose=False):
        #     logger.warning(f"Failed to turn on LR for ASIC {_asic}")

    # -- Set up DAQ ------------------------------------------------
    # data_coll_en: 0x03, turn on data collection for ASIC 0 and 1
    # trig_coll_en: 0x00, turn off trigger collection
    # daq_fcmd:     0b01001011, L1A
    # gen_preimp_en:0, turn off pre-fcmd
    # ---------------------------------------------------------------
    if not packetlib.send_check_DAQ_gen_params(cmd_outbound_conn, data_cmd_conn, h2gcroc_ip, h2gcroc_port, fpga_addr=fpga_address, data_coll_en=(1<<total_asic)-1, trig_coll_en=0x00, daq_fcmd=gen_fcmd_L1A, gen_preimp_en=0x01, gen_pre_interval=gen_pre_interval_value, gen_nr_of_cycle=gen_nr_cycle, gen_interval=gen_interval_value, gen_pre_fcmd=gen_fcmd_internal_injection, gen_fcmd=gen_fcmd_L1A, daq_push_fcmd=gen_fcmd_L1A, machine_gun=machine_gun, ext_trg_en=0, ext_trg_deadtime=10000, verbose=False):
        logger.warning("Failed to set up generator")
    else:
        logger.info("Generator set up successfully")

    # ! ready to start the DAQ
    # ! --------------------------------------------------------------
    phase_scan_times = [[] for _ in range(76* total_asic)]
    phase_scan_adcs = [[] for _ in range(76 * total_asic)]
    phase_scan_tots = [[] for _ in range(76 * total_asic)]
    phase_scan_toas = [[] for _ in range(76 * total_asic)]
    phase_scan_adc_errs = [[] for _ in range(76 * total_asic)]
    phase_scan_tot_errs = [[] for _ in range(76 * total_asic)]
    phase_scan_toa_errs = [[] for _ in range(76 * total_asic)]

    for _phase in phase_settings:
        logger.info(f"Phase setting: {_phase}")
        for _asic in range(total_asic):
            scan_config[_asic]["top_reg_offLR"][7]  = _phase & 0x0F
            scan_config[_asic]["top_reg_runLR"][7]  = _phase & 0x0F

        # for _asic in range(total_asic):
        #     if not packetlib.send_check_i2c_wrapper(cmd_outbound_conn, data_cmd_conn, h2gcroc_ip, h2gcroc_port, asic_num=_asic, fpga_addr = fpga_address, sub_addr=packetlib.subblock_address_dict["Top"], reg_addr=0x00, data=scan_config[_asic]["top_reg_offLR"], retry=i2c_retry, verbose=False):
        #         logger.warning(f"Failed to turn off LR for ASIC {_asic}")

        # caliblib.quick_iodelay_setting(cmd_outbound_conn, data_cmd_conn, h2gcroc_ip, h2gcroc_port, _fpga_addr=fpga_address, _asic_num=total_asic, _good_setting_window_len=40)
        
        for _asic in range(total_asic):
            if not packetlib.send_check_i2c_wrapper(cmd_outbound_conn, data_cmd_conn, h2gcroc_ip, h2gcroc_port, asic_num=_asic, fpga_addr = fpga_address, sub_addr=packetlib.subblock_address_dict["Top"], reg_addr=0x00, data=_asic_config["top_reg_runLR"], retry=i2c_retry, verbose=False):
                logger.warning(f"Failed to turn on LR for ASIC {_asic}")


        inj_adc_list, inj_adc_err_list, inj_tot_list, inj_tot_err_list, inj_toa_list, inj_toa_err_list = caliblib.Inj_2V5(cmd_outbound_conn,data_cmd_conn, data_data_conn, h2gcroc_ip, h2gcroc_port, fpga_address, 12, dac_value, scan_start_chn, scan_chn_numbers_per_asic, total_asic, scan_chn_pack, machine_gun, expected_event_number, i2c_fragment_life, scan_config, channel_not_used, dead_channel_list, i2c_dict, logger, i2c_retry)

        for _asic in range(total_asic):
            if not packetlib.send_check_i2c_wrapper(cmd_outbound_conn, data_cmd_conn, h2gcroc_ip, h2gcroc_port, asic_num=_asic, fpga_addr = fpga_address, sub_addr=packetlib.subblock_address_dict["Top"], reg_addr=0x00, data=scan_config[_asic]["top_reg_offLR"], retry=i2c_retry, verbose=False):
                logger.warning(f"Failed to turn off LR for ASIC {_asic}")

        for _asic in range(total_asic):
            for _chn_asic in range(scan_start_chn, scan_chn_numbers_per_asic + scan_start_chn):
                _chn = _asic * 76 + _chn_asic
                if _chn in channel_not_used:
                    continue
                if _chn in dead_channel_list:
                    continue
                inj_adc_samples = inj_adc_list[_chn]
                inj_adc_err_samples = inj_adc_err_list[_chn]
                inj_tot_samples = inj_tot_list[_chn]
                inj_tot_err_samples = inj_tot_err_list[_chn]
                inj_toa_samples = inj_toa_list[_chn]
                inj_toa_err_samples = inj_toa_err_list[_chn]

                phase_offseted = _phase - phase_offset
                if phase_offseted < 0:
                    phase_offseted += 16

                for _sample_index in range(len(inj_adc_samples)):
                    if inj_adc_samples[_sample_index] == 0:
                        continue
                    phase_scan_times[_chn].append(phase_offseted * phase_time_interval + _sample_index * sample_time_interval)
                    phase_scan_adcs[_chn].append(inj_adc_samples[_sample_index])
                    phase_scan_adc_errs[_chn].append(inj_adc_err_samples[_sample_index])
                    phase_scan_tots[_chn].append(inj_tot_samples[_sample_index])
                    phase_scan_tot_errs[_chn].append(inj_tot_err_samples[_sample_index])
                    phase_scan_toas[_chn].append(inj_toa_samples[_sample_index])
                    phase_scan_toa_errs[_chn].append(inj_toa_err_samples[_sample_index])

    logger.info("Injection completed")
    fig, axs = plt.subplots(3, 1, figsize=(9, 18))
    fig.subplots_adjust(hspace=0.4)

    run_number = 1
    csv_file_name = os.path.join(output_dump_folder, f"inj_adc_samples_{fpga_address+208}_{scan_chn_numbers_per_asic}_{dac_value}_{run_number}.csv")
    with open(csv_file_name, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["Channel", "Time", "Phase", "ADC", "TOT_10bit", "TOT_12bit", "ToA"])
        # print the results
        _channel_in_plot = 0
        fig_group_of_eight, ax_group_of_eight = plt.subplots(1, 1, figsize=(9, 6))
        for _asic in range(total_asic):
            for _chn_asic in range(scan_start_chn, scan_chn_numbers_per_asic + scan_start_chn):

                _chn = _asic * 76 + _chn_asic
                _times = phase_scan_times[_chn]
                _adcs = phase_scan_adcs[_chn]
                # if pedestal_subtraction:
                #     _adc_pedestal = np.mean(_adcs[0:10])
                #     _adcs = _adcs - _adc_pedestal + pedestal_setting
                _tots = phase_scan_tots[_chn]
                _toas = phase_scan_toas[_chn]
                _adc_errs = phase_scan_adc_errs[_chn]
                _tot_errs = phase_scan_tot_errs[_chn]
                _toa_errs = phase_scan_toa_errs[_chn]
                # sort by time
                if _times and _adcs and _tots and _toas and _adc_errs and _tot_errs and _toa_errs:
                    _times, _adcs, _tots, _toas, _adc_errs, _tot_errs, _toa_errs = zip(*sorted(zip(_times, _adcs, _tots, _toas, _adc_errs, _tot_errs, _toa_errs)))
                else:
                    logger.warning(f"One or more lists are empty for channel {_chn}, skipping sorting and unpacking.")
                    continue
                _times = np.array(_times)
                _adcs = np.array(_adcs)
                _tots = np.array(_tots)
                _toas = np.array(_toas)
                _adc_errs = np.array(_adc_errs)
                _tot_errs = np.array(_tot_errs)
                _toa_errs = np.array(_toa_errs)

                # write the results to the csv file
                for i in range(len(_times)):
                    # _phase = (_times[i] / phase_time_interval) - float(int(_times[i] / phase_time_interval))
                    # _phase = int(_phase * 16) + phase_offset
                    # if _phase > 15:
                    #     _phase -= 16
                    # writer.writerow([_chn, _times[i], _phase, _adcs[i], _tots[i], _toas[i]])
                    tot_10bit = _tots[i]
                    tot_12bit = decompress_tot(tot_10bit)
                    _phase = int(((_times[i] % sample_time_interval) / phase_time_interval) + phase_offset) % 16 
                    writer.writerow([_chn, _times[i], _phase, _adcs[i], tot_10bit, tot_12bit, _toas[i]])

                if pedestal_subtraction:
                    _adc_pedestal = np.mean(_adcs[0:10])
                    _adcs = _adcs - _adc_pedestal + pedestal_setting
                    _adc_errs = np.array([abs(x) for x in _adc_errs])
                
                axs[0].errorbar(_times, _adcs, yerr=_adc_errs, fmt='-o', label=f'Channel {_chn}', alpha=0.5, markersize=2)
                axs[1].errorbar(_times, _tots, yerr=_tot_errs, fmt='o',  label=f'Channel {_chn}', alpha=0.5, markersize=2)
                axs[2].errorbar(_times, _toas, yerr=_toa_errs, fmt='o',  label=f'Channel {_chn}', alpha=0.5, markersize=2)

                if _channel_in_plot == 0:
                    fig_group_of_eight, ax_group_of_eight = plt.subplots(1, 1, figsize=(9, 6))
                
                label_text = f"Chn {_chn}"
                if _chn % 38 == 0:
                    label_text += "(CM)"
                elif _chn % 38 == 19:
                    label_text += "(CALIB)"
                ax_group_of_eight.errorbar(_times, _adcs, yerr=_adc_errs, fmt='-o', label=label_text, alpha=0.5, markersize=2)
                _channel_in_plot += 1

                if _channel_in_plot == 8:
                    ax_group_of_eight.set_xlabel("Time [ns]")
                    ax_group_of_eight.set_ylabel("ADC")
                    ax_group_of_eight.set_ylim(0, 1023)
                    ax_group_of_eight.set_xlim(-1, (machine_gun + 1) * phase_time_interval * 16 + 1)
                    ax_group_of_eight.grid( linestyle='--')
                    ax_group_of_eight.legend( loc='upper right', fontsize='small')
                    pdf_file.savefig(fig_group_of_eight)
                    plt.close(fig_group_of_eight)
                    _channel_in_plot = 0

    
    axs[0].set_title('ADC Samples')

    axs[1].set_title('TOT Samples')

    axs[2].set_title('ToA Samples')

    # set y range
    axs[0].set_ylim(0, 1023)
    axs[1].set_ylim(0, 1023)
    axs[2].set_ylim(0, 1023)
    # set x range
    axs[0].set_xlim(-1, (machine_gun + 1) * phase_time_interval * 16 + 1)
    axs[1].set_xlim(-1, (machine_gun + 1) * phase_time_interval * 16 + 1)
    axs[2].set_xlim(-1, (machine_gun + 1) * phase_time_interval * 16 + 1)

    for ax in axs:
        ax.grid( linestyle='--')

    # Save the figure to a PDF file
    pdf_file.savefig(fig)
    plt.close(fig)

    # ! --------------------------------------------------------------

    # for _asic in range(total_asic):
    #     if not packetlib.send_check_i2c_wrapper(cmd_outbound_conn, data_cmd_conn, h2gcroc_ip, h2gcroc_port, asic_num=_asic, fpga_addr = fpga_address, sub_addr=packetlib.subblock_address_dict["Top"], reg_addr=0x00, data=scan_config[_asic]["top_reg_offLR"], retry=i2c_retry, verbose=False):
    #         logger.warning(f"Failed to turn off LR for ASIC {_asic}")

finally:
    pool_do("unregister", "data", pc_data_port)
    pool_do("unregister", "cmd", pc_cmd_port)
    data_cmd_conn.close()
    data_data_conn.close()
    cmd_outbound_conn.close()
    ctrl_conn.close()
    pdf_file.close()
    