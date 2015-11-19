import numpy as np 

class ReadBeamform:
     """ A class to read, correlate, and process CHIME vdif data. 
     """

     def __init__(self, pmin=0, pmax=1e7):
          # Dumb way of setting total number of 
          # packets to read from each file. 1e7 should get to end.
          self.pmax = pmax 
          self.pmin = pmin
          self.nfr = 8 # Number of links 
          self.npol = 2
          self.nfq = 8 # Number of frequencies in each frame
          self.nfreq = 1024 # Total number of freq
          self.nmm = 625
          self.frame_size = 5032 # Frame size in bytes

     @property
     def header_dict(self):
          """ Dictionary with header info. Each entry has a
          length-three list ordered [word_number, bit_min, bit_max]. 
          i.e. the 8b word number in the 32-byte VDIF header followed 
          by the bit range within the word.
          """
          header_dict = {'time'    : [0, 0, 29],
                         'epoch'   : [1, 24, 29],
                         'frame'   : [1, 0, 23],
                         'link'    : [3, 16, 19],
                         'slot'    : [3, 20, 25],
                         'station' : [3, 0, 15],
                         'eud2'    : [5, 0, 32]
                         }

          return header_dict

     def bit_manip(self, x, k, l):
          """ Select only bits k from the right to
          l from the left.
          """
          return (x / 2**k) % 2**(l - k)

     def parse_header(self, header):
          """ Take header binary parse it 

          Returns
          -------
          station : int 
               polarization state (0 or 1)
          link : int
               freq index, increases packet to packet 
          slot : int
               node number 
          frame : int
               frame index
          time : int 
               time after reference epoch in seconds
          count : int
               fpga count               
          """
          # Should be 8 words long
          head_int = np.fromstring(header, dtype=np.uint32) 

          hdict = self.header_dict

          t_ind = hdict['time']
          frame_ind = hdict['frame']
          stat_ind = hdict['station']
          link_ind = hdict['link']
          slot_ind = hdict['slot']
          eud2_ind = hdict['eud2']

          station = self.bit_manip(head_int[stat_ind[0]], stat_ind[1], stat_ind[2])
          link = self.bit_manip(head_int[link_ind[0]], link_ind[1], link_ind[2])
          slot = self.bit_manip(head_int[slot_ind[0]], slot_ind[1], slot_ind[2])
          frame = self.bit_manip(head_int[frame_ind[0]], frame_ind[1], frame_ind[2])
          time = self.bit_manip(head_int[t_ind[0]], t_ind[1], t_ind[2])
          count = self.bit_manip(head_int[eud2_ind[0]], eud2_ind[1], eud2_ind[2])

          return station, link, slot, frame, time, count

     def open_pcap(self, fn):
          """ Reads in pcap file with dpkt package
          """
          f = open(fn)

          return dpkt.pcap.Reader(f)

     def str_to_int(self, raw):
          """ Read in data from packets as signed 8b ints

          Parameters
          ----------
          raw : binary
               Binary data to be read in 

          Returns
          -------
          data : array_like
               np.float32 arr [Re, Im, Re, Im, ...]
          """
          raw = np.fromstring(raw, dtype=np.uint8)

          raw_re = (((raw >> 4) & 0xf).astype(np.int8) - 8).astype(np.float32)
          raw_im = ((raw & 0xf).astype(np.int8) - 8).astype(np.float32)

          data = np.zeros([2*len(raw_re)], dtype=np.float32)
          data[0::2] = raw_re
          data[1::2] = raw_im

          return data

     def freq_ind(self, slot_id, link_id, frame):
          """ Get freq index (0-1024) from slot number,
          link number, and frame.
          """
          link_id = link_id[:, np.newaxis]
          frame = frame[np.newaxis]

          return slot_id + 16 * link_id + 128 * frame


     def read_file(self, fn):
          """ Get header and data from a pcap file 

          Parameters
          ----------
          fn : np.str 
               file name

          Returns
          -------
          header : array_like
               (nt, 5) array, see self.parse_header
          data : array_like
               (nt, ntfr * 2 * nfq)
          """
          pcap = self.open_pcap(fn)

          header = []
          data = []

          k = 0

          for ts, buf in pcap:
               k += 1

               if (k >= self.pmax):
                    break
               if (k < self.pmin):
                    continue

               eth = dpkt.ethernet.Ethernet(buf)
               ip = eth.data
               tcp = ip.data
               
               # Instead of tcp, open the file, read in 5032 bytes
               # after an open

               header.append(self.parse_header(tcp.data[:32]))
               data.append(self.str_to_int(tcp.data[32:])[np.newaxis])

          if len(header) >= 1:
               
               data = np.concatenate(data).reshape(len(header), -1)
               header = np.concatenate(header).reshape(-1, 6)

               return header, data

     def read_file_dat(self, fn):
          """ Get header and data from .dat file
   
          Parameters  
          ----------
          fn : np.str 
               file name                                                                 

          Returns
          -------                                                                                                                                          
          header : array_like
               (nt, 6) array, see self.parse_header
          data : array_like 
               (nt, ntfr * 2 * nfq)                                                                                                                                                     
          """
          fo = open(fn)

          header = []
          data = []
          
          for k in range(np.int(self.pmax)):

               data_str = fo.read(self.frame_size)

               if len(data_str) == 0:
                    print "Fin File"
                    break

               header.append(self.parse_header(data_str[:32]))
               data.append(self.str_to_int(data_str[32:])[np.newaxis])

          if len(header) >= 1:

               data = np.concatenate(data).reshape(len(header), -1)
               header = np.concatenate(header).reshape(-1, 6)

               return header, data

     def J2000_to_unix(self, t_j2000):
          """ Takes seconds since J2000 and returns 
          a unix time
          """
          J2000_unix = 946728000.0

          return t_j2000 + J2000_unix

     def rebin_time(self, arr, trb):
          """ Rebin data array in time
          """
          nt = arr.shape[0]
          rbshape = (nt//trb, trb, ) + arr.shape[1:]

          arr = arr[:nt // trb * trb].reshape(rbshape)

          return arr.mean(1)

     def get_times(self, header, seq=True):
          """ Takes two time columns of header (seconds since
          J2000 and packet number) and constructs time array in
          seconds

          Parameters
          ----------
          header : 

          seq : boolean
               If True, use fpga sequence number. Else use vdif timestamp
          """
          times = header[:, -3]/np.float(self.nmm) + header[:, -2].astype(np.float)

          if seq is True:
               seq = header[:, -1] 
               times = (seq - seq[0]) / 625.0**2 + times[0]

          return self.J2000_to_unix(times)

     def correlate_xy(self, data_r, data_i, header, indpol0, indpol1):

          seq0 = header[indpol0, -1]
          seq1 = header[indpol1, -1]
#          seq1 = seq0.copy()

          XYreal = []
          XYimag = []
          
          seq_xy = []

          data_rp0 = data_r[indpol0]
          data_ip0 = data_i[indpol0]

          data_rp1 = data_r[indpol1]
          data_ip1 = data_i[indpol1]

          for t0, tt in enumerate(seq0):

               t1 = np.where(seq1 == tt)[0]

               if len(t1) < 1:
                    continue

               seq_xy.append(tt)

               xyreal = data_rp0[t0] * data_rp1[t1] + data_ip0[t0] * data_ip1[t1]
               xyimag = data_ip0[t0] * data_rp1[t1] - data_rp0[t0] * data_ip1[t1]

               XYreal.append(xyreal)
               XYimag.append(xyimag)

          times = header[indpol0, -3]/np.float(self.nmm) 
          times += header[indpol0, -2].astype(np.float)

          tt_xy = (seq_xy - seq_xy[0]) / 625.0**2 + times[0]

          return XYreal, XYimag, self.J2000_to_unix(tt_xy)


     def correlate_and_fill(self, data, header, trb=1):
          """ Take header and data arrays and reorganize
          to produce the full time, pol, freq array

          Parameters
          ----------
          data : array_like
               (nt, ntfr * 2 * self.nfq) array of nt packets
          header : array_like
               (nt, 5) array, see self.parse_header
          ntimes : np.int
               Number of packets to use

          Returns 
          -------
          arr : array_like (duhh) np.float64
               (ntimes * ntfr, npol, nfreq) array of autocorrelations
          tt : array_like 
               Same shape as arr, since each frequency has its own time vector
          """

          slots = set(header[:, 2])

          print "Data has", len(slots), "slots: ", slots

          data_real = data[:, 0::2]
          data_imag = data[:, 1::2]

          data_corr = data_real**2 + data_imag**2
          data_corr = data_corr.reshape(-1, 625, 8).mean(1)

          data_real = data_real.reshape(-1, 625, 8).transpose((0, 2, 1))
          data_imag = data_imag.reshape(-1, 625, 8).transpose((0, 2, 1))

          arr = np.zeros([data_corr.shape[0] / self.nfr / 2 / len(slots) + 256
                                   , 2*self.npol, self.nfreq], np.float64)

          tt = np.zeros([data_corr.shape[0] / self.nfr / 2 / len(slots) + 256
                                   , 2*self.npol, self.nfreq], np.float64)

          for qq in range(self.nfr):

               for ii in range(16):

                    fin = ii + 16 * qq + 128 * np.arange(8)

                    indpol0 = np.where((header[:, 0]==0) & \
                                            (header[:, 1]==qq) & (header[:, 2]==ii))[0]

                    indpol1 = np.where((header[:, 0]==1) & \
                                            (header[:, 1]==qq) & (header[:, 2]==ii))[0]
                    
                    inl = min(len(indpol0), len(indpol1))

                    if inl < 1:
                         continue

                    indpol0 = indpol0[:inl]
                    indpol1 = indpol1[:inl]
                    
                    XYreal, XYimag, tt_xy = self.correlate_xy(
                                 data_real, data_imag, header, indpol0, indpol1)

                    XYreal = np.concatenate(XYreal, axis=0)
                    XYimag = np.concatenate(XYimag, axis=0)

                    arr[:len(indpol0), 0, fin] = data_corr[indpol0]
                    arr[:len(indpol1), 3, fin] = data_corr[indpol1]

                    arr[:len(XYreal), 1, fin] = XYreal.mean(-1)
                    arr[:len(XYimag), 2, fin] = XYimag.mean(-1)

                    tt[:len(tt_xy), 1, fin] = np.array(tt_xy).repeat(8).reshape(-1, 8)
                    tt[:len(tt_xy), 2, fin] = tt[:len(tt_xy), 1, fin].copy()

                    if (len(indpol0) >= 1) and (len(indpol0) < arr.shape[0]): 
                         tt[:len(indpol0), 0, fin] = self.get_times(\
                                         header[indpol0]).repeat(8).reshape(-1, 8)

                    if (len(indpol1) >= 1) and (len(indpol1) < arr.shape[0]):
                         tt[:len(indpol1), 3, fin] = self.get_times(\
                                         header[indpol1]).repeat(8).reshape(-1, 8)


          return arr, tt


     def correlate_and_reorg(self, header, data):
          """ 
          """
          assert data.shape[-1] == 8

          seq = list(set(header[:, -1]))
          seq.sort()


          npackets = (seq[-1] - seq[0]) / 625

#          times = (seq - seq[0]) / 625.**2 #+ self.get_times(header[0])

          seq_f = np.arange(seq[0], seq[-1], 625)

          Arr = np.zeros([npackets, 2, self.nfreq])

          for pp in range(self.npol):
               for qq in range(self.nfr):
                    for ii in range(16):
                         for tt in range(len(seq_f)):
                              ind = np.where((header[:, 0]==pp) & (header[:, 1]==qq) & \
                                                (header[:, 2]==ii) & (header[:, -1]==seq_f[tt]))[0]

                              fin = ii + 16 * qq + 128 * np.arange(8)
                         
                              if len(ind) != 1:
                                   continue
                         
                              Arr[tt, pp, fin] = data[ind]

          return Arr

     def fill_arr(self, header, data, ntimes=None, trb=1):
          """ Take header and data arrays and reorganize
          to produce the full time, pol, freq array

          Parameters
          ----------
          header : array_like
               (nt, 5) array, see self.parse_header
          data : array_like
               (nt, ntfr * 2 * self.nfq) array of nt packets
          ntimes : np.int
               Number of packets to use

          Returns 
          -------
          arr : array_like (duhh) np.float64
               (ntimes * ntfr, npol, nfreq) array of autocorrelations
          """

          ntfr = data.shape[-1] // (2 * self.nfq)

          data_corr = data[:ntimes, 0::2]**2 + data[:ntimes, 1::2]**2
          ntimes = data_corr.shape[0]

          header = header[:ntimes]

          data_corr = data_corr[:ntimes // (self.nfr*self.npol) * self.nfr 
                                 ].reshape(-1, self.nfr, self.npol, ntfr, self.nfq)

          data_corr = data_corr.transpose((0, 3, 2, 1, 4)
                                 ).reshape(-1, self.npol, self.nfr * self.nfq)

          pos = np.arange(self.nfr)
          f_ind = self.freq_ind(header[0, 2], np.arange(self.nfq), pos).reshape(-1)

          arr = np.zeros([data_corr.shape[0], self.npol, self.nfreq], np.float64)
          arr[..., f_ind] = data_corr

          del data_corr

          return self.rebin_time(arr, trb)

     def corrbin(self, data):
          """ Take data, square and sum to produce
          two autocorrelations.
          """

          data_corr = data[:, 0::2]**2 + data[:, 1::2]**2

          data_corr = data_corr.reshape(-1, 625, 8).mean(1)

          return data_corr

def MJD_to_unix(MJD):
     
     return (MJD + 2400000.5 - 2440587.5) * 86400.0

def unix_to_MJD(t_unix):
     
     return (t_unix / 86400.0) + 2440587.5 - 2400000.5

