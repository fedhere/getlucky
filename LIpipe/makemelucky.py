#################################################################
###############written by fbb, dkudrow, shillberry########################
#Reads all of the images in a directory, sorts them by Strehl
#Ratio or consecutive order, and stacks the specified top percent
#either aligned to a guide star, correlating in fourier space, 
#or not aligning, weighting if requested.
#This version includes: 
#detripling for compact binaries, drizzle algorithm for 
#subpixel alignment  and dynamic guide region.
#Type $python stacked.py -h for usage
####
#last modified 11/14/2011
#################################################################


print 'Initializing stacking sequence...'

import sys,os,time
import pyfits as PF
from numpy import *
from scipy import *
from scipy.interpolate import interp1d
from scipy.fftpack import fft2, ifft2
import threading
import multiprocessing
import Queue
import matplotlib
matplotlib.use('Agg')
from pylab import plt, axvline, savefig, subplot,  figure, plot, legend, title, hist, imshow, show
sys.path.append("../LIHSPcommon")
from myutils import readconfig, mygetenv, mymkdir
from myioutils import *
from mysciutils import *

from time import time

print 'Loaded all packages'
DEBUG = False

def preppars(file0,inpath, hd):
        
#####     HEADER INFO     #####
            
    try: image=PF.open(inpath+'/'+file0)
    except:
        print "image could not be open %s/%s"%(inpath,file0)
        return -1

    header=image[0].header
    image.close()

    hd['xsize']=header['NAXIS1']
    hd['ysize']=header['NAXIS2']
    
    if  'HBIN' in header:
        hd['hbin']=float(header['HBIN'])
        hd['vbin']=float(header['VBIN'])
    elif 'CCDXBIN' in header:
        hd['hbin']=float(header['CCDXBIN'])
        hd['vbin']=float(header['CCDYBIN'])
    if 'EXPOSURE' in header:
        hd['exp']=  (header['EXPOSURE'])
    elif 'EXPTIME' in header:
        hd['exp']=  (header['EXPTIME'])
    else:
        print "no exposure length recognizable key!" 
        return -1
    if 'SATURATE' in header:
         hd['saturation']=header['SATURATE']
    hd['filename']=file0[:-9].replace('.fits','')


    return hd, header

####################################################################3

def add2stack(dx,dy,stack,newfits, w):
###NOTE: Not that this makes a difference when we are using square images,
###NOTE: but I belive both x's should be .shape[1]
##################################################################

    limx1=[0,newfits.shape[1]] #min x value of fits
    limx2=[0,newfits.shape[1]] #min y value of fits
    limy1=[0,newfits.shape[0]] #min x value of fits
    limy2=[0,newfits.shape[0]] #min y value of fits

    if dx < 0:
        limx1[0]=-dx
        limx2[1]=dx
    elif dx > 0:
        limx2[0]=dx
        limx1[1]=-dx

    if dy < 0:
        limy1[0]=-dy
        limy2[1]=dy
    elif dy > 0:
        limy2[0]=dy
        limy1[1]=-dy

    stack[limy1[0]:limy1[1],limx1[0]:limx1[1]] += w*newfits[limy2[0]:limy2[1],limx2[0]:limx2[1]]
    #stack[limx1[0]:limx1[1],limy1[0]:limy1[1]] += w*newfits[limx2[0]:limx2[1],limy2[0]:limy2[1]]

####################################################################3

def updatecentroid(bp,maxindex,name, hd): ###NEEDS TESTING
    bpx = bp[0]
    bpy = bp[1]
    rad = hd['rad']

    newbpx=bpx+maxindex[1][0]-rad
    newbpy=bpy+maxindex[0][0]-rad

    print bpx,bpy
    print newbpx,newbpy
    print hd['psx'],hd['psy']
    print hd['psxsq'], hd['psysq']
    print hd['xsize'],hd['ysize']
    print rad
    
    if (newbpx-bpx)*(newbpx-bpx)<hd['psxsq'] and (newbpy-bpy)*(newbpy-bpy)<hd['psysq']:
        if (newbpx-2*rad > 0 and newbpx+2*rad < hd['xsize'] \
            and newbpy-2*rad > 0 and newbpy+2*rad < hd['ysize'] \
            and (bpx-newbpx)*(bpx-newbpx) > rad*rad/4.0 \
            and (bpy-newbpy)*(bpy-newbpy) > rad*rad/4.0)  :

            return newbpx,newbpy
        
    else:
        print '''Cannot update centroid cause it is outside 
of the allowed region, if this is common choose 
another star or shrink the search region radius ''',name

        return (bpx,bpy)

def findbright(inpath, name, bp, hd, best, follow, nrej):
    tmpfile=PF.open(inpath+'/'+name)
    data = tmpfile[0].data
    rad=hd['rad']
    reg=data[bp[1]-rad:bp[1]+rad+1,bp[0]-rad:bp[0]+rad+1]

    t = threading.Thread(target=findbrightest, args=(reg, name, hd, bp,data, best, follow, nrej))
    
    t.daemon = True
    t.start()
    tmpfile.close()
    return [nrej,t]

def findbrightest(reg, name, hd, bp, fits, best, follow, nrej):
    bpx = bp[0]
    bpy = bp[1]
    rad = hd['rad']
    satlevel=hd['saturation']
    maxvalue =reg.max()
    if maxvalue<satlevel:
        maxindex =where(reg==reg.max())
        if DEBUG:
            print """
            

                  printing maxindev, maxvalue:


                  """
            print maxindex
            print reg.max()
	    print 'bpx = %d \nbpy = %d \nrad = %d ' %(bpx,bpy,rad)
            #print fits[bpy-rad+maxindex[0][0]-rad:\
             #                            bpy-rad+maxindex[0][0]+rad+1,\
              #                           bpx-rad+maxindex[1][0]-rad:\
               #                          bpx-rad+maxindex[1][0]+rad+1].shape

        if len(maxindex[0]) ==1: 
##### CHECKS THAT RADIUS IS NOT TOO LARGE
	    if bpy-rad+maxindex[0][0]-rad < 0 or \
		bpx-rad+maxindex[1][0]-rad < 0 or \
		 bpy-rad+maxindex[0][0]+rad+1 > fits.shape[0] or \
		  bpx-rad+maxindex[1][0]+rad+1 > fits.shape[1]:
		    print '''ERROR!!: Searching outside boundary. \nReduce radius manually.'''

                    if DEBUG:
                        print bpy-rad+maxindex[0][0]-rad, bpx-rad+maxindex[1][0]-rad , bpy-rad+maxindex[0][0]+rad+1, bpx-rad+maxindex[1][0]+rad+1, fits.shape
###############################################

            (mx,my,apf) =calccents(\
            array(fits[bpy-rad+maxindex[0][0]-rad:\
                                   bpy-rad+maxindex[0][0]+rad+1,\
                                   bpx-rad+maxindex[1][0]-rad:\
                                   bpx-rad+maxindex[1][0]+rad+1]))
            if DEBUG:
#		figure()

                imshow( fits[bpy-rad+maxindex[0][0]-2*rad:\
                                         bpy-rad+maxindex[0][0]+2*rad+1,\
                                         bpx-rad+maxindex[1][0]-2*rad:\
                                         bpx-rad+maxindex[1][0]+2*rad+1])
                show()
                
            best.append([name,
                         maxindex[1],
                         maxindex[0],
                         maxvalue,
                         int(bpx),
                         int(bpy),
                         bpx+maxindex[1][0]-2*rad+mx, 
                         bpy+maxindex[0][0]-2*rad+my, apf])
	    l = best[-1]
	    #print '%s %d %d %f %d %d %f %f %f\n'\
		#%(l[0],l[1],l[2],l[3],int(l[4]+l[1])-rad,
                 #   int(l[5]+l[2])-rad,l[6],l[7],l[8])
            if DEBUG:
                print best[-1]
            if follow=='dynamic':  #TO BE CHECKED
		bp=updatecentroid(bp,maxindex,name,hd)
                                
        else:
            print 'Repeat brightest pixel found in %s'%name+ " (maxima location at "+repr(maxindex[0])+" , "+repr(maxindex[1])+'). Frame skipped.'
            nrej+=1
    else:
        print 'Saturated  pixel found in %s. Frame skipped.' % name
        nrej+=1

def orderbystrehl(imdef, files, listfilename, hd, inpath):
    best=[]
    gsx = hd['gsx']
    gsy = hd['gsy']
    rad = hd['rad']
    nrejected0=0
    nrejected=0
    nfiles = len(files)
    if imdef['imtype'] == 'CONSEC' and imdef['align'] == 'UNALIGN':
        #consecutive analigned, not ordering
        for name in files:
            best.append([name,0,0,0,
                         gsx,gsy,gsx,gsy, 0])


    else: #aligned lucky or weighted: strehl ratio file needed 
        print '#Evaluating %s images...' % nfiles
        sys.stdout.flush()
        if os.path.isfile(listfilename):
            #file exists, reading it out
            print 'reading list of strehl sorted files'
            listfile = open(listfilename)
            sys.stdout.flush()

            lsplit=listfile.readline().split()
            if len(lsplit)<9:
                print 'old version of strehl ratio file. remove ', listfilename, 'first and rerun reduction.'
                return -1
	    try: ##looks for additional columns from corr
                best.append([lsplit[0], int(lsplit[1]), int(lsplit[2]), 
                         float(lsplit[3]), 
                         int(lsplit[4]), int(lsplit[5]),
                         float(lsplit[6]), float(lsplit[7]),
                         float(lsplit[8]),int(lsplit[9]), int(lsplit[10]), float(lsplit[11])])
                for l in listfile:
                    lsplit=l.split()
                    best.append([lsplit[0], int(lsplit[1]), int(lsplit[2]), 
                             float(lsplit[3]), 
                             int(lsplit[4]), int(lsplit[5]),
                             float(lsplit[6]), float(lsplit[7]),
                             float(lsplit[8]),int(lsplit[9]), int(lsplit[10]), float(lsplit[11])])
	    except:
	        print "WARNING: less than 12 columns in strehl ratio file. Old version (only for point source processing)"
                best.append([lsplit[0], int(lsplit[1]), int(lsplit[2]), 
                         float(lsplit[3]), 
                         int(lsplit[4]), int(lsplit[5]),
                         float(lsplit[6]), float(lsplit[7]),
                         float(lsplit[8])])
                for l in listfile:
                    lsplit=l.split()
                    best.append([lsplit[0], int(lsplit[1]), int(lsplit[2]), 
                             float(lsplit[3]), 
                             int(lsplit[4]), int(lsplit[5]),
                             float(lsplit[6]), float(lsplit[7]),
                             float(lsplit[8])])
                    
        else: #creating a strehl ratio
            print "creating strehl ratio"
            bp=(gsx,gsy)
            name = files[0]
            tmpfile=PF.open(inpath+'/'+name)
	    data = tmpfile[0].data
            nrejected0=0
            reg=data[bp[1]-rad:bp[1]+rad+1,bp[0]-rad:bp[0]+rad+1]

##### CHECKS FOR OUTPUT DIRECTORY
	    path = os.path.dirname(listfilename)
	    if not os.path.isdir(path):
		if mymkdir(path) != 0:
		    print '''\n\nWARNING: output directory does not exist \n %s\nRectify before re-running the pipeline.''' %path
		    sys.exit() 

            if DEBUG:
                print '''


                '''
                print inpath+'/'+name
                figure()
                imshow(reg)
#                savefig("test.png")
                show()
                
            findbrightest(reg,  name, hd, bp,data, best, imdef['follow'], nrejected0) 

            for name in files[1:]:
                #if len(best) == 1:
                    #printreg(name,imdef['follow'],inpath, best,rad, bp,'red')

                t = findbright(inpath, name, bp, hd, best, imdef['follow'], nrejected0)[1]


            t.join() #this forces code to wait for last thread to finish
 
##########PRINTING STREHL LIST######################
            print 'printing list of selected images to '+listfilename
            sys.stdout.flush()
           
            listout=open(listfilename,'w')
               
            if imdef['imtype'] !='CONSEC':
                best=sorted(best,key=lambda list:list[3] ,reverse=True)
            else :
                best=sorted(best,key=lambda list:list[0] ,reverse=False)
            for l in best:
                strhere = '%s %d %d %f %d %d %f %f %f %d %d 0.0\n'%(
                    l[0],l[1],l[2],l[3],int(l[4]+l[1])-rad,
                    int(l[5]+l[2])-rad,l[6],l[7],l[8],-99e9,-99e9)

                listout.write(strhere)
            listout.close()
    return best, nrejected0
######################################################################
######################################################################
def phase_correct(axis, radius, shifts, r):
    '''phase_correct(axis, radius, shifts, r) In the event of a possibly incorrect shift, uses peak detection on the cross-power spectrum to find additional correlations'''

    print 'Running peak detect...'
    maxtab, maxmat = peakdetect2d(r, radius)

    k = 1
    while (abs(shifts[0]) > radius or abs(shifts[1]) > radius) \
               and k < len(maxtab):
        phase = maxtab[k][0]
        print "phase = " + str(phase)

### Checks if image has negative shift ### 
        if phase[0] > axis[0]/2:
            shifts[0] =  phase[0] - axis[0]
        else:
            shifts[0] = phase[0]

        if phase[1] > axis[1]/2:
            shifts[1] = phase[1] - axis[1]
        else:
            shifts[1] = phase[1]

        k+=1

        print "...shift in NAXIS1 = %d"  %shifts[1]
        print "...shift in NAXIS2 = %d"  %shifts[0]

    if abs(shifts[0]) > radius or abs(axis1_shift) > radius:
        print 'No good correlation found. Omitting frame'
        _OMIT_ = True
        error.write('No good correlation found for ' + fnames[i] + ' ... frame omitted.\n')

    return [shifts[0], shifts[1], _OMIT_]
######################################################################
def combine(shifts, images):
    '''Parameters: [axis2_shift,axis1_shift] and [image0,image1] to be combined according to appropriate shifts. Shifts correspond to image1 correlated to image0'''

    axis2_shift = shifts[0]
    axis1_shift = shifts[1]
    stack = images[0]
    fitspad = images[1]

    if axis2_shift >= 0:
        if axis2_shift == 0: axis2_shift = -fitspad.shape[0]
        if axis1_shift >= 0:
            if axis1_shift == 0: axis1_shift = -fitspad.shape[1]
            stack[axis2_shift:,axis1_shift:] += \
            fitspad[:-axis2_shift,:-axis1_shift]
        else: #axis1_shift < 0
            stack[axis2_shift:,:-abs(axis1_shift)] += \
            fitspad[:-axis2_shift,abs(axis1_shift):]
    else: #axis2_shift < 0
        if axis1_shift >= 0:
            if axis1_shift == 0: axis1_shift = -fitspad.shape[1]
            stack[:-abs(axis2_shift),axis1_shift:] += \
            fitspad[abs(axis2_shift):,:-axis1_shift]
        else: #axis1_shift < 0
            stack[:-abs(axis2_shift),:-abs(axis1_shift)] += \
            fitspad[abs(axis2_shift):,abs(axis1_shift):]

    return stack
######################################################################
def makefft(data, fast):
    '''Quick operator to make fast fourier transform (FFT) either using PyFFTW3 (if available) or otherwise scipy.fftpack'''

    if fast:
        data = np.array(data, complex)
        fft = np.zeros(data.shape, complex)
        plan = fftw3.Plan(data, fft, 'forward')
        plan.execute()
    else:
        fft = fft2(data)

    return fft
######################################################################
queue = Queue.Queue()
class corrImages(threading.Thread):
    def __init__(self, mm, inpath, luckies, queue, ID, hd, fast):
        threading.Thread.__init__(self)
        self.master = mm
	self.inpath = inpath
        self.luckies = luckies
        self.queue = queue
        self.ID = ID
	self.hd = hd
	self.fast = fast

    def run(self):
        try:
            submaster = PF.getdata(self.inpath+'/'+self.luckies[0][0])
        except:
            print 'Cannot find image %s\nAborting...'\
                %(self.inpath+'/'+self.luckies[0][0])
            sys.exit()

        _PAD_ = 50
        alpha = 0.3
	radius = 50

	##### create submaster for threaded substack #####
        submaster = drizzle(submaster,0)
        tukeypad = pad(tukey2d(submaster.shape,alpha), _PAD_)
        submaster = pad(submaster, _PAD_)

        submasterfft = makefft(submaster*tukeypad, self.fast)

        naxis2 = submaster.shape[0]
        naxis1 = submaster.shape[1]
        nimages = len(self.luckies)
	nomit = nimages-1
        radius = self.hd['rad']
	    

	#### correlate submaster to spool master for reference shift ####
        shift1= [0,0]
        shift1[0], shift1[1], r = correlate([self.master, submasterfft], self.fast, radius)
	shifts = [[self.luckies[0][0],shift1]]

        for i in range(1, nimages):
            try:
                fits = PF.getdata(self.inpath+'/'+self.luckies[i][0])
            except:
                print 'Cannot find image %s\nAborting...' \
                        %(self.inpath + '/'+ self.luckies[i][0])
                sys.exit()

            fits = drizzle(fits, 0)
            fitspad = pad(fits, _PAD_)

            fitsfft = makefft(fitspad*tukeypad, self.fast)

            #### correlate stack image to submaster ####
            axis2_shift, axis1_shift, reg =  correlate([self.master, fitsfft], self.fast, radius)
	    
            _OMIT_ = False
            #### frame selection inactive ####
	    selection = False 
	    if selection:
                maxval = reg[axis2_shift,axis1_shift]
                stdev = reg[axis2_shift:axis2_shift+1,:].std()
                stdev = reg.std()
                if abs(maxval/stdev) < 3:
                    print 'Sufficient maximum not obtained.\nOmitting frame %s' %(self.luckies[i][0])
                    _OMIT_ = True

            #if abs(axis2_shift) > (naxis2/2 - 100) or \
            #   abs(axis1_shift) > (naxis1/2 - 100):
            #       axis2_shift, axis1_shift, _OMIT_ = \
            #       phase_correct((naxis2, naxis1), radius,\
            #                  (axis2_shift, axis1_shift), r)
            # if shift is abnormally large, run phase_correct

	    if DEBUG:
	        print 'Running %d/%d' %(i, nimages-1)
                print '\n... ' + name + '\n' + \
                      'Finding phase...\n' + \
                      '...shift in NAXIS1 = ' +str(int(axis1_shift))+ '\n' + \
                      '...shift in NAXIS2 = ' +str(int(axis2_shift))
	    if not _OMIT_: 
		nomit -= 1
		shifts.append([self.luckies[i][0],[axis2_shift,axis1_shift]])
	
	    del fits, fitspad, reg

	self.queue.put([shifts,nomit,self.ID])
	self.queue.task_done()
	
######################################################################
######################################################################
def corrcoadd(luckies, inpath, coffs, header, pc, hd, outfiles, weights, imdef, fast, outpath):

#### import and use PyFFTW3 if specified ####
    if fast:
	sys.path.append("../../Downloads/PyFFTW3-0.2.1/build/lib") 
	   ##path to PyFFTW3##
	import fftw3 
	print 'Using Fast Fourier Transforms of the West package ...'

    if DEBUG:
        phasedata = open(outpath+'/phase_correlation.dat','w')
        phasedata.write('Masterfits: ' + luckies[0][0]+'\n')

    mcoff = max(coffs)
    _PAD_ = 50
    alpha = 0.3

    global mastername
    mastername = luckies[0][0]
    try: 
	masterdata = PF.getdata(inpath+'/'+luckies[0][0])
    except:
        print """Cannot find image %s\nAborting...""" %(inpath+'/'+luckies[0][0])
        return -1    

    masterdata = drizzle(masterdata, 0)
    stack = pad(masterdata, _PAD_)
############ TUKEY WINDOW MASTER ############
    if DEBUG: print "alpha = %f" %alpha
   
######## INITIALIZE READIN VARIABLE #########
    global readin 
    readin = False
    if len(luckies[0])>9:
	if luckies[0][9]!=-99e9:
	    readin = True

    pcn=0
    if 'WEIGHTED' in imdef['imtype']:
        w=weights[0]
    else:
        w=1.0
	
    exposure = hd['exp']*w
    cumm_shift, temp_cumm = 0.0,0.0 #cumulative shift for averaging
    naxis2 = stack.shape[0]
    naxis1 = stack.shape[1]
    starttime = time()

####### CORRELATE IMAGES IN THREADING ######
    if not readin:
	print 'Finding correlations...'
        tukey = pad(tukey2d(masterdata.shape, alpha), _PAD_)
	masterfft = makefft(stack*tukey, fast)
    
        nstacks = multiprocessing.cpu_count()
        imgperth = int(round(float(mcoff)/nstacks))
        if DEBUG: 
	    print "Start threading..."
            print '%d images per each of %d stacks' %(imgperth, nstacks)


        prev = 1
        k = 1 ## k serves as thread ID number
        while k <= nstacks:
            top = min([prev+imgperth,int(mcoff)])
            if k==nstacks and top!=mcoff: top=int(mcoff)
            current = luckies[prev:top]
            if DEBUG:
	        print "Slicing [%d:%d]   len = %d" %(prev,top,len(current))
                ##print "current = %s" %str(current)

	    thread = corrImages(masterfft, inpath, current, queue, k, hd, fast)
            thread.start()

            k+=1
            prev+=imgperth

        thread.join() ## waits for final thread to finish

        allshifts = []
        nomit = queuegot = 0
        while queuegot < nstacks:
	### ID helps sorting to account for threads finishing at different times
	    [tempshift, tempomit, ID] = queue.get()
	    queuegot += 1
	    allshifts.append([tempshift,ID])
    	    nomit += tempomit

######### RUN UNTIL NOMIT IS 0 #########
        while nomit > 0:
    	    print '%d frames omitted. Starting additional thread...' %nomit
	    addnames = fnames[top:top+nomit]
	    top += nomit
	    thread = corrImages(masterfft, inpath, current, \
			    queue, k, hd, fast)
	    thread.start()
	    k+=1

	    thread.join()
	    [tempshift, nomit, ID] = queue.get()
	    allshifts.extend([tempshift,ID])

	### sort allshift groups by ID
        allshifts = sorted(allshifts, key=lambda x:x[1])
	## removes IDs from groups, but shifts are still in groups from queue
        allshifts = [x[0] for x in allshifts]
	## put group elements 1by1 into final list
        shifts = []
        for i in range(len(allshifts)):
            shifts.extend(allshifts[i])


    else: #readin corr shifts from strehl ratio list
	print 'Reading shifts from strehl list...'
        luckrange = range(len(luckies))
	shifts = [ [luckies[i][0], [luckies[i][9],luckies[i][10]]] for i in luckrange ]

    print 'Combining images...'
    for l in range(len(shifts)):
	try:
	    fits = PF.getdata(inpath+'/'+shifts[l][0])
	    fitspad = pad(drizzle(fits,0),_PAD_)
	except:
	    print 'Cannot find %s.\nAborting...'\
		%(inpath+'/'+shifts[l][0])

	w = weights[l+1] ##+1 accounts for master image offset
	stack = combine(shifts[l][1],[stack,fitspad*w])
	exposure += hd['exp']*w

        if DEBUG: #writes shift information to data sheet 
	    phasedata.write('%s ( %d , %d )\n' \
		%(shifts[l][0],shifts[l][1][0], shifts[l][1][1]))

        
	if l+2 in coffs: 
	##l+1+1 : first 1 accounts for index offset. 
        ##        Second 1 accounts for master image offset.
            a = (l+2)/sum(weights[:l+2])
	    header['NUMKIN'] = l+2
            writefitsout(header, exposure*a, pc[pcn], hd, outfiles[pcn], stack*a, imdef)
	    pcn+=1

    print 'Done threading... took %f seconds for %d images' %(time()-starttime,l+2)
        
    
def stackonbright(coff, luckies, hd, pc, mcoff, weights, header, imdef, outfile,inpath):    
    rad=hd['rad']
    gsx,gsy=hd['gsx'],hd['gsy']
    dx,dy=rad,rad

    try: masterdata = PF.getdata(inpath+'/'+luckies[0][0])
    except:
        print """Cannot find image %s\nAborting...""" %('/'+luckies[0][0])
        return -1    
    pcn=0
    if 'WEIGHTED' in imdef['imtype']:
	w = weights[0]
    else:
	w=1.0
    exposure = hd['exp']*w
    _PAD_ = 50
    
    stack = pad(drizzle(masterdata,0), _PAD_)
    #stack = np.zeros([2*(x+_PAD_) for x in masterdata.shape], float) 

    if imdef['imtype']=='CONSEC':
        luckies=sorted(luckies,key=lambda list:list[0] ,reverse=False)


    mcoff = min (mcoff,len(luckies))
    if DEBUG: 
        nameroot = outfile[0]
        nameroot = nameroot[:nameroot.index('all')+3]
        star_shift = open(nameroot+'/star_shift_data.dat','w')

    for k in xrange(1,mcoff):
        if 'WEIGHTED' in imdef['imtype']:
            w=weights[k]
        else:
            w=1.0

        if DEBUG: print 'Running %d/%d...' %(k, mcoff-1)
        name=luckies[k][0]
        tmp=PF.getdata(inpath+'/'+name)
            
        fitspad = pad(drizzle(tmp,0),_PAD_)

        if imdef['follow']=='dynamic': #TO BE CHECKED
                dx=2*(luckies[k][4]-gsx+luckies[k][1])
                dy=2*(luckies[k][5]-gsy+luckies[k][2])
                x=luckies[k][4]-rad+luckies[k][1]
                y=luckies[k][5]-rad+luckies[k][2]

        else:
    
                dx=2*(luckies[k][1]-luckies[0][1])
                dy=2*(luckies[k][2]-luckies[0][2])
                #            x=gsx-rad+luckies[k][1]
                #            y=gsy-rad+luckies[k][2]


	if DEBUG: star_shift.write('%s [ %d , %d ]\n' %(name, -dy, -dx))

        add2stack(dx,dy,stack,fitspad, w)
        exposure +=w*hd['exp']


        if k+1 in coff:
            a =  (k+1)/sum(weights[:k+1])

            writefitsout(header, exposure*a, pc[pcn], hd, outfile[pcn], stack*a, imdef)
            #writefitsout(header, exposure*a, imdef['imtype'], pc[pcn], imdef['align'], imdef['detrip'], hd, imdef['follow'], outfile[pcn], stack*a)
            pcn+=1

#######################################################################
def createstack(inpath,gsx,gsy,rad,select,pc,shift,detrip,minsep,outpath,coresz,follow,ps, saturation, fast):

    if mymkdir(outpath) != 0:
        print '''\n\nWARNING: output directory cannot be created \n %s\nRectify before re-running the pipeline.''' %path
        sys.exit()
    fitsoutpath=outpath+'/x%d_y%d_r%d/'%(gsx, gsy, rad)

    if mymkdir(fitsoutpath) != 0:
        print '''\n\nWARNING: output directory cannot be created \n %s\nRectify before re-running the pipeline.''' %path
        sys.exit()
    print "searching for files in %s"%inpath

    
    files = sorted([x for x in os.listdir(inpath) if x.endswith('.fits')])
    nfiles=len(files)
    #print 'nfiles = %s' %str(files)
    print inpath
##        crating percentages list   #####
    if type(pc) is float or type(pc) is int:
        pc = [pc]

### caluclating corresponding number of images to stack   #####
    cutoff = zeros(len(pc), float)
    for i,c in enumerate(pc): 
        cutoff[i] = int(c/100.0*nfiles)
        if cutoff[i]==0:
            cutoff[i]=1

#####  reading in header parameters
#    hd =  dict('hbin'=9.9e99,'vbin'=9.9e99,'exp'=9.9e99,'xsize'=9.9e99,'ysize'=9.9e99, 'filename'='', 'bp[0]y'=9.9e99, 'bp[1]'=9.9e99, 'psx'=9.9e99,'psy'=9.9e99,'gsx'=gsx,'gsy'=gsy, 'coresz'=coresz, 'minsep'=minsep,'saturation'=9.9e99)
            
    hd =  dict(gsx=gsx,gsy=gsy, coresz=coresz, minsep=minsep,saturation=saturation, rad=rad)

    print preppars(files[0],inpath,hd)
    hd, header =preppars(files[0],inpath, hd)

    if hd['gsx'] == 0:
        hd['gsx'] = int(hd['xsize']/2)
    if hd['gsy'] == 0:
        hd['gsy'] = int(hd['ysize']/2)

    if hd == -1:
        return -1
    outname=hd['filename']        
##setting centroid for brightest pixel search####
#value in pixel of 2''*2'' to contain centroid update within 2'' , x and y
    hd['psx'] = 2.0/(ps*hd['hbin'])
    hd['psy'] = 2.0/(ps*hd['vbin'])
    hd['psxsq']=hd['psx']*hd['psx']
    hd['psysq']=hd['psy']*hd['psy']

#setting selet par

    imdef=dict(align='UNALIGN', imtype='', follow=follow, detrip='NONE')
    if detrip == 'v':
        imdef['detrip']='VERT'
    elif detrip == 'h':
        imdef['detrip']='HORZ'
    if shift == 'align':
        imdef['align']='ALIGN'
    if select=='lucky':
        imdef['imtype']='LUCKY'
        if shift == 'none':
            print """Will not perform lucky imaging without aligning frames
                 Changing parameter 'shift' to '1'"""
            shift = 'align'
            align='ALIGN'
            imdef['align']='ALIGN'
    elif select == 'coadded':
        imdef['imtype']='CONSEC'
    elif select == 'weighted':
        imdef['imtype']='WEIGHTED_TIPTILT'
        if shift == 'none':
            print """Will not perform weighted tip/tilt imaging without 
                 aligningframes
                 Changing parametes 'shift' to '1'"""
            shift = 'align'
            align='ALIGN'
            imdef['align']='ALIGN'
    elif select == 'corr' or select == 'correlate':
	imdef['imtype']='LUCKY_CORRELATED'
        if shift == 'none' :
            print """Will not perform kucky imaging without aligning frames.
                      Changing parameter 'shift' to '1'"""
            shift = 'align'
            align='ALIGN'
            imdef['align']='ALIGN'

    else:
        print "invalid 'select' paramter (%s): use 'coadded' for standard stacking, 'lucky' for lucky, 'weighted' for weighted average exposures, 'corr' for lucky with phase correlation"%select
        return -1  

    


################creating name files that will be useful later
    outfiles=[]
    if detrip == 'v' or detrip == 'h':
        for p in pc:
            outfiles.append(fitsoutpath+outname+'_%3.2f_%s_%s_%s_d%s.fits' % (float(p),imdef['imtype'],imdef['align'],imdef['follow'], imdef['detrip']))
    else:
        for p in pc:
            outfiles.append(fitsoutpath+'/'+outname+'_%3.2f_%s_%s_%s.fits' % (float(p),imdef['imtype'],imdef['align'],imdef['follow']))

    histfile = fitsoutpath+'/'+outname+'_'+imdef['follow']+'.hist.png' 
    listfilename = '%s/strehl_list_%s_%d_%d_%d.dat' %(inpath,imdef['follow'], gsx, gsy, rad)
    #listfilename = '%s/strehl_list_%s.dat' %(outpath,imdef['follow'])
    
    if DEBUG:
        print """DEBUG


              pritning parameters


              """
        print prnDict(hd)
        print prnDict(imdef)

################selecting best frames####################
    best, nrejected=orderbystrehl(imdef, files, listfilename, hd, inpath)

    mcoff=int(max(cutoff))
    if mcoff > nfiles-nrejected: 
        mcoff=nfiles-nrejected
    print "maximum cutoff", mcoff
    luckies=best[:mcoff]
    exposure =  0.0
    print '%d images selected (or less).' % mcoff
    sys.stdout.flush()

#########creating weights as AS^2.4 according to Robert Tubbs### TO BE CHECKED
    if imdef['imtype'] !='CONSEC' and select == 'weighted':
        weights = array(zip(*luckies)[3])
        strehlnorm = 0.3/weights[0]
        weights = pow(weights*strehlnorm,2.4)
    else:
        weights=ones(len(luckies),float)
    createhist(histfile,best)

###########detripling    TO BE CHECKED
    if detrip!='none':
        luckies,imdef['detrip'] = detripling(detrip, luckies,mcoff,hd, inpath)
        
#####     ALIGNMENT AND STACKING     #####
                            
    print """""


Compiling Lucky Image...


"""
    sys.stdout.flush()
    if select=='corr' or select=='correlate':
        print 'Using phase correlation...'
        print '\nmaximum length of fits list: %d' %mcoff
        print 'masterfits: %s' %luckies[0][0]
        corrcoadd(best, inpath, cutoff, header, pc, hd, outfiles, weights, imdef, fast, outpath)


    else:  
        print 'Using brightest pixel to align...'
        print '\nmaximum length of fits list: %d' %mcoff
        print 'masterfits: %s' %luckies[0][0]
        stackonbright(cutoff, luckies, hd, pc, mcoff, weights, header, imdef, outfiles, inpath) 


    return 1


########################################################
########################################################
########################################################
########################################################
    

if __name__ == '__main__':
    import optparse

    parser = optparse.OptionParser(usage='makelucky.py -c configfilename', conflict_handler="resolve")

    parser.add_option('-c','--configfile' , type="string",
                      help='full name to configuration file')
    parser.add_option('--debug', default=False, action="store_true",
                      help='debug')
    
    options,  args = parser.parse_args()

    if len(args)>0 or options.configfile == None:
        sys.argv.append('--help')
        options,  args = parser.parse_args() 

        print """Usage. Requires: 
                **name of parameter file conatining :**
		
                Directory containing images
		dark file
		dark method
		Guide star x coordinate
		Guide star y coordinate
		region dimensions x
		percentage of images to be selected (0-100)
		lucky: \'lucky\',\'weighted\', \'coadded\', \'corr\' 
		shift: \'align\' or \'none\'
                detripling: \'v\' or \'h\' or \'none\'
                minimum separation or cores
                core size for detripling (odd integer)
                dynamic guide region; 1 or 0
                saturation
		fftw3: \'y\' to use PyFFTW3 package, \
		       \'n\' to use normal SciPy FFTpack
            """
        sys.exit()

    if options.debug:
        DEBUG=True

#####     DECLARE VARIABLES     #####
    pars = readconfig(options.configfile)
    gsx=pars['x']
    gsy=pars['y']
    rad=pars['r']
    select=pars['sel']
    pc = pars['percent']
    ps = pars['ps']
    shift=pars['align']
    detrip=pars['detrip']
    minsep=float(pars['separation'])
    coresz=pars['core']
    follow=pars['centroid']
    saturation=float(pars['saturation'])

    global fast
    fast = pars['fftw3'].startswith('y')

    nameroot=pars['spool'][0]
    if nameroot.endswith('.fits'):
        nameroot = nameroot[:-5]
    print nameroot
    global outpath
    if len(pars['spool'])>1:	
	outpath = '%s/%s_all'%(mygetenv('SPEEDYOUT'),nameroot)
    else:
        outpath = '%s/%s'%(mygetenv('SPEEDYOUT'),nameroot)
    inpath='%s/unspooled/' %(outpath)
    #inpath='/science/fbianco/LIdata/%s/unspooled'%(nameroot)
    
    if len(select[0]) == 1:
        print "\nprocessing %s\n\n\n"%select
	ret = createstack(inpath,gsx,gsy,rad,select,pc,shift,detrip,minsep,outpath,coresz,follow,ps, saturation, fast)
    else:
        for sel in select:
            createstack(inpath,gsx,gsy,rad,sel,pc,shift,detrip,minsep,outpath,coresz,follow,ps, saturation, fast)

