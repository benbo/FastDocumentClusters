# -*- coding: utf-8 -*-
import time
import os,sys
import itertools
import math
import argparse
import numpy as np
from multiprocessing import Pool
from hashlib import sha1
import random, struct
from random import sample,choice
from sklearn import metrics

#we truncate sha1 for now. We should probably replace this with a proper hash function.
M_PRIME = (1 << 89) - 1 #(x << n) is x shifted left by n bit
MAX_HASH = (1 << 64) - 1

NUM_PERM=100
random.seed(427)
A,B = np.array([(random.randint(1, M_PRIME),random.randint(0, M_PRIME)) for _ in range(NUM_PERM)]).T

#############
# functions #
#############

def set_permutations(numperm):
    NUM_PERM=numperm
    A,B = np.array([(random.randint(1, M_PRIME),random.randint(0, M_PRIME)) for _ in range(NUM_PERM)]).T


def get_permuted_hashes(token):
    # get a hash value
    #abusing sha1 and truncating to 12 digit number
    hv=int(sha1(token).hexdigest(),16)% (10 ** 12)
    #do Carter and Wegman like hashing.
    return np.bitwise_and((A * hv + B) % M_PRIME,MAX_HASH)


def get_clusters(fn):
    with open(fn,'r') as f:
        next(f)#skip header
        for line in f:
            a=line.split(',')
            yield a[0],a[2]

def get_lsh(sig,nbands):
    for i,band in enumerate(np.array_split(sig,nbands)):
        yield sha1("ab" + str(band) + "ba"+str(i)).digest()
         
def get_bandwidth(n, tr):
        """
        Threshold tr = (1/b) ** (1/r) where
        b #bands
        r #rows per band
        n = b * r  #elements in signature
        """
        best = n, 1
        minerr  = float("inf")
        for r in range(1, n + 1):
            try:
                b = 1. / (tr ** r)
            except: 
                return best
            err = abs(n - b * r)
            if err < minerr:
                best = r
                minerr = err
        return best


def connected(seed,lshdict,doc2lsh,t):
    '''
    Computes clusters based on the lsh bucket candidates.
    We do not actually check the full connected component. 
    We only check for similar docs amongst the lsh candidates for each cluster member.
    '''
    cluster=set([seed])
    #get candidates and flatten list
    base=set([seed])
    while len(base)>0:
        s=base.pop()
        #get candidates and flatten list
        candidates=set(itertools.chain.from_iterable([lshdict[sig] for sig in doc2lsh[s]]))
        m1=hashcorp[s]
        for cand in candidates:
            if cand in cluster:continue#don't check if we've already added this
            m2=hashcorp[cand]
            if jaccard(m1,m2) >=t:
                cluster.add(cand)
                base.add(cand)
    #all candidates have been checked 
    return cluster 

def jaccard(h1,h2):
    '''
    Compute jaccard similarity between two minhash signatures.
    Make sure to only compute jaccard similarity for hashes created with same hash functions (i.e. same seed for random permutation)
    '''
    return np.float(np.count_nonzero(h1==h2)) /np.float(h2.size)

def near_duplicates(seed,lshdict,doc2lsh,t):
    cluster=set([seed])
    #get candidates and flatten list
    candidates=set(itertools.chain.from_iterable([lshdict[sig] for sig in doc2lsh[seed]]))
    m1=hashcorp[seed]
    for cand in candidates:
        if cand in cluster:continue#don't check if we've already added this
        m2=hashcorp[cand]
        if jaccard(m2,m1) >=t:
            cluster.add(cand)
    #all candidates have been checked 
    return cluster

    
def compute_clusters(obj):
    thr=obj[0]
    bandwidth=get_bandwidth(NUM_PERM, thr)#r
    bands=int(math.ceil(float(NUM_PERM)/float(bandwidth)))#b
    print("starting calculations for threshold "+str(thr)+"\nnumber of lsh bands: "+str(bands))
    sys.stdout.flush()

    start_time = time.time()
    doc_to_lsh={}
    lsh_dict={}

    for key,m in hashcorp.items():
        #compute lsh 
        signatures = [sig for sig in get_lsh(m,bands)]
        #store signatures for this document
        doc_to_lsh[key]=signatures
        #store lsh signature to key
        for sig in signatures:
            if sig in lsh_dict:
                lsh_dict[sig].append(key)
            else:
                lsh_dict[sig]=[key]
    print(("Calculating lsh signatures for threshold "+str(thr)+" took\n ---%s seconds ---\n" % (time.time() - start_time)))
    sys.stdout.flush()

    

    #compute connected components
    start_time = time.time()
    doc2cluster={}
    count=0

    for doc in hashcorp:
        if doc not in doc2cluster:
            cl=connected(doc,lsh_dict,doc_to_lsh,thr)
            doc2cluster.update({i:count for i in cl })
            count+=1
    print(("Computing connected components for threshold: "+str(thr)+" took\n--- %s seconds ---\n" % (time.time() - start_time)))
        
    print("write results to file")
    start_time = time.time()
    f=open(outdir+'/doc2cluster_'+str(thr)+'_'+suffix+'.csv','w')
    f.write('line,cluster\n')
    for key, value in doc2cluster.items():
        f.write(str(key)+','+str(value)+'\n')
    f.close()
    print(("Writing results to files for threshold "+str(thr)+" took:\n--- %s seconds ---\n" % (time.time() - start_time)))
    
                
#Set up command line arguments
parser = argparse.ArgumentParser(description='Calculate connected components of documents with given threshold(s)')
parser.add_argument("-t", dest="threshold",type=float,help="threshold for ER", metavar="T")
parser.add_argument("-lt", dest="lt",type=float,help="lower threshold for ER", metavar="TL")
parser.add_argument("-ut", dest="ut",type=float,help="upper threshold for ER", metavar="TU")
parser.add_argument("-out", dest="out",help="output directory", metavar="OUT")
parser.add_argument("-steps", dest="steps",type=float,help="number of steps between lower and upper threshold", metavar="TSTEP")
parser.add_argument("-sigl", dest="num_permutations",type=int,help="minhash signature length", metavar="SIG")
parser.add_argument("-suff", dest="suffix",help="output file suffix", metavar="S")
parser.add_argument("-infile", dest="infile",help="input file",required=True, metavar="IF")
parser.add_argument('-header', dest='header', action='store_true')
parser.add_argument('-near_dups', dest='near_dups',help="Do near duplicate detection. If this is not set, connected components will be computed", action='store_true')
parser.add_argument("-p", dest="nump", required=False,type=int,help="number of processes for multithreading", metavar="NUMP")
parser.set_defaults(match=False)
parser.set_defaults(header=True)
parser.set_defaults(near_dups=True)
parser.set_defaults(threshold=None)
parser.set_defaults(num_permutations=100)
parser.set_defaults(lt=0.0)
parser.set_defaults(ut=1.0)
parser.set_defaults(steps=2)
parser.set_defaults(nump=1)
parser.set_defaults(suffix='')
parser.set_defaults(out='out')

if __name__ == "__main__":    
    #fetch command line arguments
    args = parser.parse_args()
    num_processes=args.nump
    suffix=args.suffix
    if NUM_PERM!=args.num_permutations:
        set_permutations(args.num_permutations)

    #create output directory if it does not exist
    outdir=args.out
    if not os.path.exists(outdir):
        os.makedirs(outdir)

    thresholds=[]
    lt=args.lt
    near_dups=args.near_dups
    ut=args.ut
    steps=args.steps
    if args.threshold is not None:
        thresholds=[args.threshold]
    else:
        if None in [lt,ut,steps]: 
            print("need lower threshold, upper threshold, and number of steps")
            exit()
        else:
            thresholds=np.linspace(lt, ut, num=steps)

    #load text. Flat file for now
    print('load text')
    start_time = time.time()
    with open(args.infile,'r') as f:
        if args.header:
            next(f)
        #TODO test robustness
        #mycorpus=[(i,set(line.encode('utf8', 'ignore').lower().split())) for i,line in enumerate(f)]
        mycorpus=[(i,set(line.lower().split())) for i,line in enumerate(f)]

    print(("--- %s seconds ---" % (time.time() - start_time)))

    print('Calculate minhash signatures')
    start_time = time.time()

    #prepare dictionary of hashes
    hashcorp=dict.fromkeys([tup[0] for tup in mycorpus])
    #compute hashes
    for key,doc in mycorpus:
        #compute minhash signature
        hashvalues=np.empty(NUM_PERM)
        hashvalues.fill(MAX_HASH)
        for token in doc:
            #np.minimum(get_permuted_hashes(token.encode('utf-8','ignore')), hashvalues)
            np.minimum(get_permuted_hashes(token), hashvalues)
        hashcorp[key]=hashvalues
    print(("--- %s seconds ---" % (time.time() - start_time)))
    if num_processes> 1:
        if len(thresholds)<num_processes:
            num_processes=len(thresholds)
        p=Pool(num_processes)
        assignment=[ (x,) for x in thresholds]
        p.map(compute_clusters,assignment)
    else:
        for x in thresholds:
            compute_clusters((x,))

