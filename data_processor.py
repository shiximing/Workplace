import numpy as np
import pandas as pd
import os
import re
import struct
import xml.etree.ElementTree as ET
import scipy.fft as sfft
import scipy.signal as ssignal

class DataProcessor:
    @staticmethod
    def clean_data(data):
        if data is None or len(data) == 0:
            return data
        return np.nan_to_num(data, nan=0.0, posinf=0.0, neginf=0.0)

    @staticmethod
    def parse_fstrm(file_path):
        try:
            with open(file_path, 'rb') as f:
                header_data = b""
                while b"[Data]" not in header_data:
                    chunk = f.read(1024)
                    if not chunk: break
                    header_data += chunk
                
                data_tag_idx = header_data.find(b"[Data]")
                if data_tag_idx == -1:
                    raise Exception("未找到 [Data] 标记")
                
                header_str = header_data[:data_tag_idx].decode('ascii', errors='ignore')
                f.seek(data_tag_idx + len(b"[Data]") + 1)
                
                time_interval = 0.0002
                chan_dict = {}
                lines = header_str.splitlines()
                for line in lines:
                    if line.startswith("TimeInterval="):
                        try: time_interval = float(line.split("=")[1])
                        except: pass
                    m = re.match(r"Channel (\d+)=([^;\n]+)", line)
                    if m:
                        chan_dict[int(m.group(1))] = m.group(2).strip()
                
                if not chan_dict:
                    match = re.search(r"XMLAsHex;([0-9a-fA-F]+)", header_str)
                    if match:
                        xml_bytes = bytes.fromhex(match.group(1))
                        xml_root = ET.fromstring(xml_bytes.decode('utf-8', errors='ignore'))
                        for chan in xml_root.findall(".//Channel"):
                            chan_dict[int(chan.get("Index", 0))] = chan.get("Name")

                if not chan_dict:
                    raise Exception("无法解析通道信息")
                
                sorted_indices = sorted(chan_dict.keys())
                channels = [chan_dict[i] for i in sorted_indices]
                raw_data = np.fromfile(f, dtype=np.float32)
                num_channels = len(channels)
                num_samples = len(raw_data) // num_channels
                data_matrix = raw_data[:num_samples * num_channels].reshape(-1, num_channels)
                df = pd.DataFrame(data_matrix, columns=channels)
                
                if "Time in recording [s]" not in df.columns:
                    if "Time" in df.columns:
                        df.rename(columns={"Time": "Time in recording [s]"}, inplace=True)
                    else:
                        df["Time in recording [s]"] = np.arange(len(df)) * time_interval
                
                return df, time_interval
        except Exception as e:
            raise ValueError(f"FSTRM 解析错误: {e}")

    @staticmethod
    def parse_csv(file_path):
        try:
            encodings = ['utf-8', 'gbk', 'utf-16']
            content = None
            current_enc = 'utf-8'
            for enc in encodings:
                try:
                    with open(file_path, 'r', encoding=enc) as f:
                        content = f.readlines()
                        current_enc = enc
                        break
                except: continue
            
            if not content: raise ValueError("无法读取文件")

            header_idx = -1
            sampling_freq = 5000.0
            for i, line in enumerate(content):
                if '#Recording frequency' in line:
                    try: sampling_freq = float(line.split(',')[1].strip())
                    except: pass
                if '[g]' in line or 'Time in recording' in line:
                    header_idx = i
                    break
            
            if header_idx == -1: raise ValueError("未找到数据表头")
            
            df = pd.read_csv(file_path, skiprows=header_idx, encoding=current_enc)
            df.columns = [c.strip() for c in df.columns]
            if df.columns[0].startswith('#'):
                cols = list(df.columns)
                cols[0] = cols[0][1:]
                df.columns = cols
            
            return df, 1.0/sampling_freq
        except Exception as e:
            raise ValueError(f"CSV 解析错误: {e}")

    @staticmethod
    def calculate_fft(data, sampling_freq):
        n = len(data)
        if n < 10: return np.array([]), np.array([])
        data_detrended = ssignal.detrend(data)
        window = ssignal.get_window('hann', n)
        windowed_data = data_detrended * window
        sum_w = np.sum(window)
        norm_factor = 2.0 / sum_w if sum_w > 0 else 0
        fft_values = sfft.rfft(windowed_data)
        magnitudes = np.abs(fft_values) * norm_factor
        frequencies = sfft.rfftfreq(n, d=1/sampling_freq)
        return frequencies, magnitudes

    @staticmethod
    def calculate_psd(data, sampling_freq):
        if len(data) < 10: return np.array([]), np.array([])
        nperseg = min(len(data), 1024)
        frequencies, psd_values = ssignal.welch(data, fs=sampling_freq, window='hann', nperseg=nperseg)
        return frequencies, psd_values
