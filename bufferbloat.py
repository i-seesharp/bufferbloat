#!/usr/bin/python
"CS244 Spring 2015 Assignment 1: Bufferbloat"

from mininet.topo import Topo
from mininet.node import CPULimitedHost
from mininet.link import TCLink
from mininet.net import Mininet
from mininet.log import lg, info
from mininet.util import dumpNodeConnections
from mininet.cli import CLI
from mininet.clean import cleanup

from subprocess import Popen, PIPE
from time import sleep, time
from multiprocessing import Process
from argparse import ArgumentParser

from monitor import monitor_qlen
import termcolor as T

import sys
import os
import math

# TODO: Don't just read the TODO sections in this code.  Remember that
# one of the goals of this assignment is for you to learn how to use
# Mininet. :-)

parser = ArgumentParser(description="Bufferbloat tests")
parser.add_argument('--bw-host', '-B',
                    type=float,
                    help="Bandwidth of host links (Mb/s)",
                    default=1000)

parser.add_argument('--bw-net', '-b',
                    type=float,
                    help="Bandwidth of bottleneck (network) link (Mb/s)",
                    required=True)

parser.add_argument('--delay',
                    type=float,
                    help="Link propagation delay (ms)",
                    required=True)

parser.add_argument('--dir', '-d',
                    help="Directory to store outputs",
                    required=True)

parser.add_argument('--time', '-t',
                    help="Duration (sec) to run the experiment",
                    type=int,
                    default=10)

parser.add_argument('--maxq',
                    type=int,
                    help="Max buffer size of network interface in packets",
                    default=100)

# Linux uses CUBIC-TCP by default that doesn't have the usual sawtooth
# behaviour.  For those who are curious, invoke this script with
# --cong cubic and see what happens...
# sysctl -a | grep cong should list some interesting parameters.
parser.add_argument('--cong',
                    help="Congestion control algorithm to use",
                    default="reno")

# Expt parameters
args = parser.parse_args()

class BBTopo(Topo):
    "Simple topology for bufferbloat experiment."

    def build(self, n=2):
        # Here are two hosts
        hosts = []
        for i in range(1,n+1):
            hosts.append(self.addHost('h%d'%(i)))

        # Here I have created a switch.  If you change its name, its
        # interface names will change from s0-eth1 to newname-eth1.
        switch = self.addSwitch('s0')


        # TODO: Add links with appropriate characteristics

        isHostBW = [True] #The first host bw 
        for i in range(n-1):
            isHostBW.append(False)
        for i in range(1,n+1):
            bw_arg = args.bw_net
            if isHostBW[i-1]:
                bw_arg = args.bw_host
            
            self.addLink(hosts[i-1], switch, bw=bw_arg, delay=args.delay, max_queue_size=args.maxq)

def compute_average(lst):
    #A helper function to compute the average of the download times.
    total = 0.0
    for elem in lst:
        total += elem
    return float(total)/float(len(lst))            

def compute_stddev(lst):
    #A helper function to compute the standard deviation of the download times.
    avg = compute_average(lst)
    total = 0.0
    for elem in lst:
        total = total + (elem - avg)**2
    var = float(total)/float(len(lst))
    return var**0.5

def get_webpage(net):
    h1 = net.get('h1')
    h2 = net.get('h2')
    #After we have received the host objects. we can the server's IP
    h1_IP = h1.IP()
    popen = h2.popen('curl -o /dev/null -s -w %%{time_total} %s/http/index.html' % h1_IP)
    return popen #return the popen object containing the time.

# Simple wrappers around monitoring utilities.  You are welcome to
# contribute neatly written (using classes) monitoring scripts for
# Mininet!

# tcp_probe is a kernel module which records cwnd over time. In linux >= 4.16
# it has been replaced by the tcp:tcp_probe kernel tracepoint.
def start_tcpprobe(outfile="cwnd.txt"):
    os.system("rmmod tcp_probe; modprobe tcp_probe full=1;")
    Popen("cat /proc/net/tcpprobe > %s/%s" % (args.dir, outfile),
          shell=True)

def stop_tcpprobe():
    Popen("killall -9 cat", shell=True).wait()

def start_qmon(iface, interval_sec=0.1, outfile="q.txt"):
    monitor = Process(target=monitor_qlen,
                      args=(iface, interval_sec, outfile))
    monitor.start()
    return monitor

def start_iperf(net):
    h2 = net.get('h2')
    print "Starting iperf server..."
    # For those who are curious about the -w 16m parameter, it ensures
    # that the TCP flow is not receiver window limited.  If it is,
    # there is a chance that the router buffer may not get filled up.
    server = h2.popen("iperf -s -w 16m")
    # TODO: Start the iperf client on h1.  Ensure that you create a
    # long lived TCP flow. You may need to redirect iperf's stdout to avoid blocking.

    #We need to be able to fit all the proper arguments into a string
    command = "iperf -c "
    h2_IP = h2.IP()
    #Form the command, to send to popen
    command = command + str(h2_IP) + " -t "
    command = command + str(args.time) + " > "
    command = command + str(args.dir) + "/iperf.out"
    h1 = net.get('h1')
    h1.popen(command, shell=True)

def start_webserver(net):
    h1 = net.get('h1')
    proc = h1.popen("python http/webserver.py", shell=True)
    sleep(1)
    return [proc]

def start_ping(net):
    # TODO: Start a ping train from h1 to h2 (or h2 to h1, does it
    # matter?)  Measure RTTs every 0.1 second.  Read the ping man page
    # to see how to do this.

    # Hint: Use host.popen(cmd, shell=True).  If you pass shell=True
    # to popen, you can redirect cmd's output using shell syntax.
    # i.e. ping ... > /path/to/ping.txt
    # Note that if the command prints out a lot of text to stdout, it will block
    # until stdout is read. You can avoid this by runnning popen.communicate() or
    # redirecting stdout
    h1 = net.get('h1')
    h2 = net.get('h2')
    #Execute a ping command measuring RTT through opoen every 0.1s
    popen = h1.popen("ping -i 0.1 %s > %s/ping.txt"%(h2.IP(), args.dir), shell=True)

def bufferbloat():
    if not os.path.exists(args.dir):
        os.makedirs(args.dir)
    os.system("sysctl -w net.ipv4.tcp_congestion_control=%s" % args.cong)

    # Cleanup any leftovers from previous mininet runs
    cleanup()

    topo = BBTopo()
    net = Mininet(topo=topo, host=CPULimitedHost, link=TCLink)
    net.start()
    # This dumps the topology and how nodes are interconnected through
    # links.
    dumpNodeConnections(net.hosts)
    # This performs a basic all pairs ping test.
    net.pingAll()

    # Start all the monitoring processes
    start_tcpprobe("cwnd.txt")
    start_ping(net)

    # TODO: Start monitoring the queue sizes.  Since the switch I
    # created is "s0", I monitor one of the interfaces.  Which
    # interface?  The interface numbering starts with 1 and increases.
    # Depending on the order you add links to your network, this
    # number may be 1 or 2.  Ensure you use the correct number.
    #
    # qmon = start_qmon(iface='s0-eth2',
    #                  outfile='%s/q.txt' % (args.dir))
    qmon = start_qmon(iface='s0-eth2', outfile='%s/q.txt'%(args.dir))

    # TODO: Start iperf, webservers, etc.
    start_iperf(net)
    start_webserver(net)

    # Hint: The command below invokes a CLI which you can use to
    # debug.  It allows you to run arbitrary commands inside your
    # emulated hosts h1 and h2.
    #
    # CLI(net)

    # TODO: measure the time it takes to complete webpage transfer
    # from h1 to h2 (say) 3 times.  Hint: check what the following
    # command does: curl -o /dev/null -s -w %{time_total} google.com
    # Now use the curl command to fetch webpage from the webserver you
    # spawned on host h1 (not from google!)
    # Hint: have a separate function to do this and you may find the
    # loop below useful.
    download_popens = [] #collection of all popen objects which consist of the fetch times
    start_time = time() #record the start time
    
    while True:
        #Execution pauses for 1 second-then on every 2nd second - it fetches the webpage
        #Yield a fetch once every 2 seconds
        sleep(2)
        iter_popen = get_webpage(net)
        download_popens.append(iter_popen)
        #We move the calls to communicate, outside of the loop because 
        #the call wastes time/introduces delay preventing us from actually calling
        #get_webpage once every 2 seconds.
        now = time()
        delta = now - start_time
        if delta > args.time:
            break
        print "%.1fs left..." % (args.time - delta)

    #Call communicate on all popens we have from webpage fetches
    time_taken = []
    for p in download_popens:
        time_taken.append(float(p.communicate()[0]))
    print "Length of time_taken : ",len(time_taken)
    # TODO: compute average (and standard deviation) of the fetch
    # times.  You don't need to plot them.  Just note it in your
    # README and explain.
    download_file = args.dir+"/download_time.txt" #name of file where we save all the download times.
    f = open(download_file, 'w')
    for i in range(len(time_taken)):
        f.write("%s \n"%time_taken[i])
    f.close()
    #Computing Average and standard deviation
    avg_t = compute_average(time_taken)
    stddev_t = compute_stddev(time_taken)
    stats = [avg_t, stddev_t] #collection of important statistics to be written to stats.txt

    #Store the average and stddev in a file 
    file_name = args.dir+"/stats.txt"
    temp = ["Average : %2f", "Std Deviation : %2f"]
    f = open(file_name, 'w') #Write mode so everytime program runs, the file is re written
    for i in range(len(temp)):
        f.write(temp[i]%stats[i])
        f.write("\n")
    f.close()


    stop_tcpprobe()
    if qmon is not None:
        qmon.terminate()
    net.stop()
    # Ensure that all processes you create within Mininet are killed.
    # Sometimes they require manual killing.
    Popen("pgrep -f webserver.py | xargs kill -9", shell=True).wait()

if __name__ == "__main__":
    bufferbloat()
