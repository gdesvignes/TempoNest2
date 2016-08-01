from libstempo.libstempo import *
import libstempo as T
import psrchive
import numpy as np
import matplotlib.pyplot as plt
import PTMCMCSampler
from PTMCMCSampler import PTMCMCSampler as ptmcmc
import scipy as sp
import corner
import pymultinest
import math
import os
import threading, subprocess

class Likelihood(object):
    
	def __init__(self):
	
		
		self.SECDAY = 24*60*60

		self.parfile = None
		self.timfile = None
		self.psr = None  
		self.SatSecs = None
		self.SatDays = None
		self.FNames = None
		self.NToAs = None
		self.numTime = None	   
		self.TempoPriors = None

		self.ProfileData = None
		self.ProfileFData = None
		self.fftFreqs = None
		self.NFBasis = None
		self.ProfileMJDs = None
		self.ProfileInfo = None

		self.toas= None
		self.residuals =  None
		self.BatCorrs =  None
		self.ModelBats =  None

		self.designMatrix = None
		self.FisherU = None

		self.TScrunched = None
		self.TScrunchedNoise = None
		self.TScrunchedFreqs = None

		self.Nbins = None
		self.ShiftedBinTimes = None
		self.ReferencePeriod = None
		self.ProfileStartBats = None
		self.ProfileEndBats = None

		self.MaxCoeff = None
		self.MLShapeCoeff = None
		self.MeanBeta = None
		self.MeanPhase = None
		self.MeanScatter = None
		self.PhasePrior = None

		self.doplot = None
	
		self.n_params = None
		self.parameters = None
		self.pmin = None
		self.pmax = None
		self.startPoint = None
		self.cov_diag = None
		self.hess = None
		self.eigM = None
		self.eigV = None

		self.InterpolatedTime = None
		self.InterpBasis = None
		self.InterpJitterMatrix = None

		self.InterpFBasis = None
		self.InterpFJitterMatrix = None


		self.getShapeletStepSize = False
		self.TScrunchChans = None

		self.EvoRefFreq = 1400.0
		self.EvoNPoly = 0
		self.TScrunchShapeErr = None

		self.chains = None
		self.ShapePhaseCov = None
		self.returnVal  = 0;

		#Model Parameters

		self.fitNCoeff = False
		self.fitNComps = False
		self.NScatterEpochs = 0
		self.ScatterInfo = None

	import time, sys

	# update_progress() : Displays or updates a console progress bar
	## Accepts a float between 0 and 1. Any int will be converted to a float.
	## A value under 0 represents a 'halt'.
	## A value at 1 or bigger represents 100%
	def update_progress(self, progress):
	    barLength = 10 # Modify this to change the length of the progress bar
	    status = ""
	    if isinstance(progress, int):
		progress = float(progress)
	    if not isinstance(progress, float):
		progress = 0
		status = "error: progress var must be float\r\n"
	    if progress < 0:
		progress = 0
		status = "Halt...\r\n"
	    if progress >= 1:
		progress = 1
		status = "Done...\r\n"
	    block = int(round(barLength*progress))
	    text = "\rPercent: [{0}] {1}% {2}".format( "#"*block + "-"*(barLength-block), progress*100, status)
	    sys.stdout.write(text)
	    sys.stdout.flush()


	def loadPulsar(self, parfile, timfile):
		self.psr = T.tempopulsar(parfile=parfile, timfile = timfile)    
		self.psr.fit()
		self.SatSecs = self.psr.satSec()
		self.SatDays = self.psr.satDay()
		self.FNames = self.psr.filename()
		self.NToAs = self.psr.nobs
		    


		#Check how many timing model parameters we are fitting for (in addition to phase)
		self.numTime=len(self.psr.pars())
		redChisq = self.psr.chisq()/(self.psr.nobs-len(self.psr.pars())-1)
		self.TempoPriors=np.zeros([self.numTime,2]).astype(np.float128)
		for i in range(self.numTime):
			self.TempoPriors[i][0]=self.psr[self.psr.pars()[i]].val
			self.TempoPriors[i][1]=self.psr[self.psr.pars()[i]].err/np.sqrt(redChisq)
			print "fitting for: ", self.psr.pars()[i], self.TempoPriors[i][0], self.TempoPriors[i][1]

		#Now loop through archives, and work out what subint/frequency channel is associated with a ToA.
		#Store whatever meta data is needed (MJD of the bins etc)
		#If multiple polarisations are present we first PScrunch.

		self.ProfileData=[]
		self.ProfileMJDs=[]
		self.ProfileInfo=[]

		print "Loading Data: "
		profcount = 0
		while(profcount < self.NToAs):

		    self.update_progress(np.float64(profcount)/self.NToAs)
		    arch=psrchive.Archive_load(self.FNames[profcount])

		    
		    npol = arch.get_npol()
		    if(npol>1):
			arch.pscrunch()
		    arch.remove_baseline()
		    nsub=arch.get_nsubint()


		    for i in range(nsub):

			if(profcount == self.NToAs):
			        break

			subint=arch.get_Integration(i)
		
			nbins = subint.get_nbin()
			nchans = subint.get_nchan()
			npols = subint.get_npol()
			foldingperiod = subint.get_folding_period()
			inttime = subint.get_duration()
			centerfreq = subint.get_centre_frequency()
		
			print "Subint Info:", profcount, i, nbins, nchans, npols, foldingperiod, inttime, centerfreq
		
			firstbin = subint.get_epoch()
			intday = firstbin.intday()
			fracday = firstbin.fracday()
			intsec = firstbin.get_secs()
			fracsecs = firstbin.get_fracsec()
			isdedispersed = subint.get_dedispersed()
		
			pulsesamplerate = foldingperiod/nbins/self.SECDAY;
		
			nfreq=subint.get_nchan()
		
			FirstBinSec = intsec + np.float128(fracsecs)
			SubIntTimeDiff = FirstBinSec-self.SatSecs[profcount]*self.SECDAY
			PeriodDiff = SubIntTimeDiff*self.psr['F0'].val
		
			if(abs(PeriodDiff) < 2.0):
			    for j in range(nfreq):
				chanfreq = subint.get_centre_frequency(j)
				toafreq = self.psr.freqs[profcount]
				prof=subint.get_Profile(0,j)
				profamps = prof.get_amps()
				
				if(np.sum(profamps) != 0 and abs(toafreq-chanfreq) < 0.001):
				    noiselevel=self.GetProfNoise(profamps)
				    self.ProfileData.append(np.copy(profamps))

				    self.ProfileInfo.append([self.SatSecs[profcount], self.SatDays[profcount], np.float128(intsec)+np.float128(fracsecs), pulsesamplerate, nbins, foldingperiod, noiselevel])                    
				    print "ChanInfo:", j, chanfreq, toafreq, np.sum(profamps), profcount
				    profcount += 1
				    if(profcount == self.NToAs):
				        break



		self.ProfileInfo=np.array(self.ProfileInfo)
		self.ProfileData=np.array(self.ProfileData)

		self.toas=self.psr.toas()
		self.residuals = self.psr.residuals(removemean=False)
		self.BatCorrs = self.psr.batCorrs()
		self.ModelBats = self.psr.satSec() + self.BatCorrs - self.residuals/self.SECDAY



		#get design matrix for linear timing model, setup jump proposal

		if(self.numTime > 0):
			self.designMatrix=self.psr.designmatrix(incoffset=False)
			for i in range(self.numTime):
				self.designMatrix[:,i] *= self.TempoPriors[i][1]
				zval = self.designMatrix[0,i]
				self.designMatrix[:,i] -= zval

			self.designMatrix=np.float64(self.designMatrix)
			N=np.diag(1.0/(self.psr.toaerrs*10.0**-6))
			Fisher=np.dot(self.designMatrix.T, np.dot(N, self.designMatrix))
			FisherU,FisherS,FisherVT=np.linalg.svd(Fisher)

			self.FisherU = FisherU

		self.ProfileStartBats = self.ProfileInfo[:,2]/self.SECDAY + self.ProfileInfo[:,3]*0 + self.ProfileInfo[:,3]*0.5 + self.BatCorrs
		self.ProfileEndBats =  self.ProfileInfo[:,2]/self.SECDAY + self.ProfileInfo[:,3]*(self.ProfileInfo[:,4]-1) + self.ProfileInfo[:,3]*0.5 + self.BatCorrs

		self.Nbins = (self.ProfileInfo[:,4]).astype(int)
		ProfileBinTimes = []
		for i in range(self.NToAs):
			ProfileBinTimes.append((np.linspace(self.ProfileStartBats[i], self.ProfileEndBats[i], self.Nbins[i])- self.ModelBats[i])*self.SECDAY)
		self.ShiftedBinTimes = np.float64(np.array(ProfileBinTimes))

		self.ReferencePeriod = np.float64(self.ProfileInfo[0][5])



	
	#Funtion to determine an estimate of the white noise in the profile data
	def GetProfNoise(self, profamps):

		Nbins = len(profamps)
		Step=100
		noiselist=[]
		for i in range(Nbins-Step):
			noise=np.std(profamps[i:i+Step])
			noiselist.append(noise)
		noiselist=np.array(noiselist)
		minnoise=np.min(noiselist)
		threesiglist=noiselist[noiselist<3*minnoise]
		mediannoise=np.median(threesiglist)
		return mediannoise



	def TScrunch(self, doplot=True, channels=1):


		self.TScrunchChans = channels
	
		minfreq = np.min(self.psr.freqs)
		maxfreq = np.max(self.psr.freqs)

		weights = 1.0/self.psr.toaerrs**2


		zipped=np.zeros([self.NToAs,2])
		zipped[:,0]=self.psr.freqs
		zipped[:,1]=weights
		zipped=zipped[zipped[:,0].argsort()]

		totalweight=np.sum(weights)
		weightsum = np.cumsum(zipped[:,1])/totalweight

		chanindices = [minfreq]
		for i in range(channels):
			chanindices.append(zipped[(np.abs(weightsum-np.float64(i+1)/channels)).argmin()][0])

		chanindices[0] -= 1
		chanindices[-1] += 1

		chanindices=np.array(chanindices)


		averageFreqs=[]
		for i in range(len(chanindices)-1):

			sub = zipped[np.logical_and(zipped[:,0] < chanindices[i+1], zipped[:,0] >= chanindices[i])]
			averageFreqs.append(np.sum(sub[:,0]*sub[:,1])/np.sum(sub[:,1]))

		averageFreqs=np.array(averageFreqs)
		self.TScrunchedFreqs = averageFreqs


		TScrunched = np.zeros([channels,np.max(self.Nbins)])

	
		totalweight = np.zeros(channels)

		profcount = 0
		print "\nAveraging All Data In Time: "
		while(profcount < self.NToAs):
	
		    self.update_progress(np.float64(profcount)/self.NToAs)
		    arch=psrchive.Archive_load(self.FNames[profcount])

		    
		    npol = arch.get_npol()
		    if(npol>1):
			arch.pscrunch()

		    arch.dedisperse()
		    arch.centre()
		    arch.remove_baseline()

		    nsub=arch.get_nsubint()


		    for i in range(nsub):

			if(profcount == self.NToAs):
			        break

			subint=arch.get_Integration(i)

			nbins = subint.get_nbin()
			nchans = subint.get_nchan()
			npols = subint.get_npol()
			foldingperiod = subint.get_folding_period()
			inttime = subint.get_duration()
			centerfreq = subint.get_centre_frequency()


			firstbin = subint.get_epoch()
			intday = firstbin.intday()
			fracday = firstbin.fracday()
			intsec = firstbin.get_secs()
			fracsecs = firstbin.get_fracsec()
			isdedispersed = subint.get_dedispersed()

			pulsesamplerate = foldingperiod/nbins/self.SECDAY;

			nfreq=subint.get_nchan()

			FirstBinSec = intsec + np.float128(fracsecs)
			SubIntTimeDiff = FirstBinSec-self.SatSecs[profcount]*self.SECDAY
			PeriodDiff = SubIntTimeDiff*self.psr['F0'].val

			if(abs(PeriodDiff) < 2.0):
			    for j in range(nfreq):
				chanfreq = subint.get_centre_frequency(j)
				toafreq = self.psr.freqs[profcount]
				prof=subint.get_Profile(0,j)
				profamps = prof.get_amps()
		
				if(np.sum(profamps) != 0 and abs(toafreq-chanfreq) < 0.001):
				    noiselevel=self.GetProfNoise(profamps)
				    weight = 1.0/noiselevel**2
				    
				    try:
					value,position = min((b,a) for a,b in enumerate(chanindices-toafreq) if b>0)
				    except:
				        value,position = (maxfreq, channels)
				        
				    totalweight[position-1] += weight
				    TScrunched[position-1] += profamps*weight

				    profcount += 1
				    if(profcount == self.NToAs):
					break

			(TScrunched.T/totalweight).T

		for i in range(channels):
			TScrunched[i] /= np.max(TScrunched[i])
		

		if(doplot == True):
			for i in range(channels):
				plt.plot(np.linspace(0,1,len(TScrunched[i])), TScrunched[i])
				plt.xlabel('Phase')
				plt.ylabel('Channel '+str(i)+' Amp')
				plt.show()	

		self.TScrunched = TScrunched
		self.TScrunchedNoise  = np.zeros(channels)
		for i in range(channels):
			self.TScrunchedNoise[i] = self.GetProfNoise(TScrunched[i])


	def FitEvoCoeffs(self, RFreq = 1400, polyorder = 1, doplot = False):

		self.EvoRefFreq = RFreq
		self.EvoNPoly = polyorder

		coeffs=self.MLShapeCoeff
		coeffs=np.array(coeffs).T

		Ncoeff=self.MaxCoeff

		RefCoeffs=np.zeros(Ncoeff)

		channels = self.TScrunchChans

		minfreq = np.min(self.psr.freqs)
		maxfreq = np.max(self.psr.freqs)

		weights = 1.0/self.psr.toaerrs**2


		zipped=np.zeros([self.NToAs,2])
		zipped[:,0]=self.psr.freqs
		zipped[:,1]=weights
		zipped=zipped[zipped[:,0].argsort()]

		totalweight=np.sum(weights)
		weightsum = np.cumsum(zipped[:,1])/totalweight

		chanindices = [minfreq]
		for i in range(channels):
			chanindices.append(zipped[(np.abs(weightsum-np.float64(i+1)/channels)).argmin()][0])

		chanindices=np.array(chanindices)
		refloc=np.abs(chanindices-RFreq).argmin()

		averageFreqs = self.TScrunchedFreqs
		refloc=np.abs(averageFreqs-RFreq).argmin()


		NewMLShapeCoeff = np.zeros([Ncoeff, polyorder+1])
		NewMLShapeCoeff[0][0] = 1
		for i in range(1,Ncoeff):

		#	coeffs[:][2][n::Ncoeff][refloc] = 10.0**-10
			line=np.zeros(len(coeffs[i]))
			c=np.polynomial.polynomial.polyfit((averageFreqs-RFreq)/1000, coeffs[i], polyorder, rcond=None, full=False, w=1.0/self.TScrunchShapeErr[i])
			NewMLShapeCoeff[i] = c
			#print i, c, coeffs[i]

			if(self.doplot == 2):
				for n in range(len(c)):
					line+=c[n]*((averageFreqs-RFreq)/1000)**n
				plt.errorbar((averageFreqs-RFreq)/1000, coeffs[i], yerr=self.TScrunchShapeErr[i],linestyle='')
				plt.errorbar((averageFreqs-RFreq)/1000, line)
				plt.show()

		self.MLShapeCoeff = NewMLShapeCoeff


	def my_prior(self, x):
	    logp = 0.

	    if np.all(x <= self.pmax) and np.all(x >= self.pmin):
		logp = np.sum(np.log(1/(self.pmax-self.pmin)))
	    else:
		logp = -np.inf

	    return logp



	def getInitialParams(self, MaxCoeff = 1, fitNComps = 1, RFreq = 1400, polyorder = 0, parameters = None, pmin = None, pmax = None, x0 = None, cov_diag = None, burnin = 1000, outDir = './Initchains/', sampler = 'pal', resume=False, incScattering = False, mn_live = 500, doplot=False):
	

		

		self.MaxCoeff = MaxCoeff
		self.fitNComps = fitNComps


		self.NScatterEpochs=0
		if(incScattering == True):
			self.NScatterEpochs=1

		if(parameters == None):
			parameters=[]
			for i in range(self.fitNComps):
				parameters.append('Phase_'+str(i))
			for i in range(self.fitNComps):
				parameters.append('Log10_Width_'+str(i))
			for i in range(self.fitNComps):
				parameters.append('NCoeff_'+str(i))

			if(incScattering == True):
				parameters.append('STau')

		print "\nGetting initial fit to profile using averaged data, fitting for: ", parameters
		n_params = len(parameters)


		if(pmin == None):
			pmin=[]
			for i in range(self.fitNComps):
				pmin.append(-0.5)
			for i in range(self.fitNComps):
				pmin.append(-3.5)
			for i in range(self.fitNComps):
				pmin.append(np.log10(1.0))
			if(incScattering == True):
				pmin.append(-6.0)


		if(pmax == None):
			pmax=[]
			for i in range(self.fitNComps):
				pmax.append(0.5)
			for i in range(self.fitNComps):
				pmax.append(0)
			for i in range(self.fitNComps):
				pmax.append(np.log10(MaxCoeff))
			if(incScattering == True):
				pmax.append(1.0)


		if(x0 == None):
			x0=[]
			for i in range(self.fitNComps):
				x0.append(0.0)
			for i in range(self.fitNComps):
				x0.append(-2)
			for i in range(self.fitNComps):
				x0.append(np.log10(50.0))
			if(incScattering == True):
				x0.append(-2.0)


		if(cov_diag == None):
			cov_diag=[]
			for i in range(self.fitNComps):
				cov_diag.append(0.1)
			for i in range(self.fitNComps):
				cov_diag.append(0.1)
			for i in range(self.fitNComps):
				cov_diag.append(0.1)
			if(incScattering == True):
				cov_diag.append(0.1)

		self.pmin = np.array(pmin)
		self.pmax = np.array(pmax)
		x0 = np.array(x0)
		cov_diag = np.array(cov_diag)


		self.doplot = 0
		self.returnVal = 0

		ML=[]

		if(sampler == 'pal'):
			sampler = ptmcmc.PTSampler(ndim=n_params,logl=self.InitialLogLike,logp=self.my_prior,
						    cov=np.diag(cov_diag**2),
						    outDir=outDir,
						    resume=resume)

			sampler.sample(p0=x0,Niter=10000,isave=10,burn=burnin,thin=1,neff=1000)

			chains=np.loadtxt(outDir+'/chain_1.txt').T

			self.chains = chains


			ML=chains.T[burnin:][np.argmax(chains[-3][burnin:])][:n_params]

		elif(sampler == 'multinest'):

			pymultinest.run(self.MNInitialLogLikeWrap, self.MNprior, n_params, importance_nested_sampling = False, resume = resume, verbose = True, sampling_efficiency = 'model', multimodal=False, n_live_points = mn_live, outputfiles_basename=outDir)

			chains=np.loadtxt(outDir+'phys_live.points').T
			ML=chains.T[np.argmax(chains[-2])][:n_params]


		self.doplot=doplot
		self.returnVal = 1

		self.MaxCoeff = np.floor(10.0**ML[2]).astype(np.int)
		self.MeanBeta = 10.0**ML[1]
		
		if(incScattering == True):
			self.MeanScatter = ML[3]

		self.MLShapeCoeff, self.TScrunchShapeErr = self.InitialLogLike(ML)
		


		self.TScrunchShapeErr = np.array(self.TScrunchShapeErr).T

		if(self.TScrunchChans > 1 and polyorder > 0):
			self.FitEvoCoeffs(RFreq, polyorder)

		if(polyorder == 0):
			newShape = np.zeros([self.MaxCoeff, 2])
			newShape[:,0] = self.MLShapeCoeff[0]
			self.MLShapeCoeff = newShape

	def TNothpl(self, n,x, pl):


		a=2.0
		b=0.0
		c=1.0
		y0=1.0
		y1=2.0*x
		pl[0]=1.0
		pl[1]=2.0*x


		for k in range(2, n):

			c=2.0*(k-1.0);

			y0=y0/np.sqrt((k*1.0))
			y1=y1/np.sqrt((k*1.0))
			yn=(a*x+b)*y1-c*y0


			pl[k]=yn
			y0=y1
			y1=yn

	  
	def Bconst(self, width, i):
		return (1.0/np.sqrt(width))/np.sqrt(2.0**i*np.sqrt(np.pi))






	def MNprior(self, cube, ndim, nparams):
		for i in range(ndim):
		        cube[i] = (self.pmax[i]-  self.pmin[i])*cube[i] + self.pmin[i]
	


	def MNInitialLogLikeWrap(self, cube, ndim, nparams):

		x=np.zeros(ndim)
		for i in range(ndim):
			x[i] = cube[i]
		return self.InitialLogLike(x)
	

	#@profile
	def InitialLogLike(self, x):


		NComps = self.fitNComps


		pcount = 0
		phase = x[pcount:pcount+NComps]


		for i in range(1, NComps):
			phase[i] = (1-phase[i-1])*phase[i]+phase[i-1]
		pcount += NComps

		width = 10.0**x[pcount:pcount+NComps]
		pcount += NComps

		FitNCoeff = np.floor(10.0**x[pcount:pcount+NComps]).astype(np.int)
		pcount += NComps

		if(self.NScatterEpochs == 1):
			STau = 10.0**x[pcount]
			pcount += 1


		loglike = 0


		'''Start by working out position in phase of the model arrival time'''

		ScrunchBins = max(np.shape(self.TScrunched))
		ScrunchChans = min(np.shape(self.TScrunched))

		FullMatrix = np.ones([1+np.sum(FitNCoeff), ScrunchBins])


		ccount = 1
		for comp in range(NComps):


			xVec = (np.linspace(-0.5,0.5-1.0/ScrunchBins, ScrunchBins) - phase[comp]) 
			xVec = ( xVec + 0.5) % (1.0) - 0.5 
			xVec /= width[comp]

			ExVec = np.exp(-0.5*(xVec)**2)
			ScaleFactors = self.Bconst(width[comp], np.arange(FitNCoeff[comp]))
	
			if(FitNCoeff[comp] > 1):
				self.TNothpl(FitNCoeff[comp], xVec, FullMatrix[ccount:ccount+FitNCoeff[comp]])

			FullMatrix[ccount:ccount+FitNCoeff[comp]] *= ExVec
			for i in range(FitNCoeff[comp]):
				FullMatrix[i+ccount] *= ScaleFactors[i]

			if(self.doplot == 1):
				for i in range(FitNCoeff[comp]):
					FullMatrix[i+ccount] /= np.std(FullMatrix[i+ccount])

			ccount+=FitNCoeff[comp]



		if(self.NScatterEpochs == 0):

			MTM = np.dot(FullMatrix, FullMatrix.T)

			Prior = 1000.0
			diag=MTM.diagonal().copy()
			diag += 1.0/Prior**2
			np.fill_diagonal(MTM, diag)
			try:
				Chol_MTM = sp.linalg.cho_factor(MTM.copy())
			except:
				return -np.inf

			if(self.returnVal == 1):
				ShapeErrs = np.sqrt(np.linalg.inv(MTM.copy()).diagonal())[1:]

			loglike = 0
			MLCoeff=[]
			MLErrs = []
			for i in range(self.TScrunchChans):

				Md = np.dot(FullMatrix, self.TScrunched[i])			
				ML = sp.linalg.cho_solve(Chol_MTM, Md)

				s = np.dot(FullMatrix.T, ML)

				r = self.TScrunched[i] - s	


				loglike  += -0.5*np.sum(r**2)/self.TScrunchedNoise[i]**2  - 0.5*np.log(self.TScrunchedNoise[i]**2)*ScrunchBins
				if(self.doplot == 1):

				    plt.plot(np.linspace(0,1,ScrunchBins), self.TScrunched[i])
				    plt.plot(np.linspace(0,1,ScrunchBins),s)
				    plt.xlabel('Phase')
				    plt.ylabel('Profile Amplitude')
				    plt.show()
				    plt.plot(np.linspace(0,1,ScrunchBins),self.TScrunched[i]-s)
				    plt.xlabel('Phase')
				    plt.ylabel('Profile Residuals')
				    plt.show()

				if(self.returnVal == 1):
				    zml=ML[1]
				    MLCoeff.append(ML[1:]/zml)
				    MLErrs.append(ShapeErrs*self.TScrunchedNoise[i]/zml)

			if(self.returnVal == 1):
			    return MLCoeff, MLErrs

		if(self.NScatterEpochs == 1):

			loglike = 0
			MLCoeff=[]
			MLErrs = []

			FullMatrix = np.fft.rfft(FullMatrix, axis=1)
			for i in range(self.TScrunchChans):
	
				ScatterScale = (self.TScrunchedFreqs[i]*10.0**6)**4/10.0**(9.0*4.0)
				STime = STau/ScatterScale
				ScatterVec = self.ConvolveExp(np.linspace(0, ScrunchBins/2, ScrunchBins/2+1)/self.ReferencePeriod, STime)

				FFTMatrix = FullMatrix*ScatterVec
				ScatterMatrix = np.fft.irfft(FFTMatrix, axis=1)

				MTM = np.dot(ScatterMatrix, ScatterMatrix.T)

				Prior = 1000.0
				diag=MTM.diagonal().copy()
				diag += 1.0/Prior**2
				np.fill_diagonal(MTM, diag)
				try:
					Chol_MTM = sp.linalg.cho_factor(MTM.copy())
				except:
					return -np.inf

				if(self.doplot == 1):
					ShapeErrs = np.sqrt(np.linalg.inv(MTM.copy()).diagonal())[1:]

				Md = np.dot(ScatterMatrix, self.TScrunched[i])			
				ML = sp.linalg.cho_solve(Chol_MTM, Md)

				s = np.dot(ScatterMatrix.T, ML)

				r = self.TScrunched[i] - s	

				#for bin in range(1024):
				#	print i, bin, self.TScrunched[i][bin], s[bin], self.TScrunchedNoise[i]


				chanlike  = -0.5*np.sum(r**2)/self.TScrunchedNoise[i]**2 - 0.5*np.log(self.TScrunchedNoise[i]**2)*ScrunchBins

				loglike += chanlike

				#print i, chanlike, self.TScrunchedNoise[i]
				if(self.doplot == 1):

				    plt.plot(np.linspace(0,1,ScrunchBins), self.TScrunched[i])
				    plt.plot(np.linspace(0,1,ScrunchBins),s)
				    plt.xlabel('Phase')
				    plt.ylabel('Profile Amplitude')
				    plt.show()
				    plt.plot(np.linspace(0,1,ScrunchBins),self.TScrunched[i]-s)
				    plt.xlabel('Phase')
				    plt.ylabel('Profile Residuals')
				    plt.show()
				    zml=ML[1]
				    MLCoeff.append(ML[1:]/zml)
				    #print ShapeErrs, ML
				    MLErrs.append(ShapeErrs*self.TScrunchedNoise[i]/zml)


			if(self.doplot == 1):
				return MLCoeff, MLErrs

		loglike -= self.TScrunchChans*np.sum(FitNCoeff)


		return loglike


	def PreComputeShapelets(self, interpTime = 1, MeanBeta = 0.1):


		print("Calculating Shapelet Interpolation Matrix : ", interpTime, MeanBeta);

		'''
		/////////////////////////////////////////////////////////////////////////////////////////////  
		/////////////////////////Profile Params//////////////////////////////////////////////////////
		/////////////////////////////////////////////////////////////////////////////////////////////
		'''

		InterpBins = np.max(self.Nbins)

		numtointerpolate = np.int(self.ReferencePeriod/InterpBins/interpTime/10.0**-9)+1
		InterpolatedTime = self.ReferencePeriod/InterpBins/numtointerpolate



		self.InterpBasis = np.zeros([numtointerpolate, InterpBins,self.MaxCoeff])
		self.InterpJitterMatrix = np.zeros([numtointerpolate,InterpBins, self.MaxCoeff])

		lenRFFT = len(np.fft.rfft(np.ones(InterpBins)))
		InterpFShapeMatrix = np.zeros([numtointerpolate, lenRFFT, self.MaxCoeff])+0j
		InterpFJitterMatrix = np.zeros([numtointerpolate,lenRFFT, self.MaxCoeff])+0j

		MeanBeta = MeanBeta*self.ReferencePeriod


		interpStep = self.ReferencePeriod/InterpBins/numtointerpolate



		for t in range(numtointerpolate):

			self.update_progress(np.float64(t)/numtointerpolate)

			binpos = t*interpStep

			samplerate = self.ReferencePeriod/InterpBins
			x = np.linspace(binpos, binpos+samplerate*(InterpBins-1), InterpBins)
			x = ( x + self.ReferencePeriod/2) % (self.ReferencePeriod ) - self.ReferencePeriod/2
			x=x/MeanBeta
			ExVec = np.exp(-0.5*(x)**2)


			hermiteMatrix = np.zeros([self.MaxCoeff+1,InterpBins])
			JitterMatrix = np.zeros([InterpBins,self.MaxCoeff])

			self.TNothpl(self.MaxCoeff+1, x, hermiteMatrix)

			hermiteMatrix *= ExVec

			for i in range(self.MaxCoeff+1):

				hermiteMatrix[i] /= np.std(hermiteMatrix[i])


			hermiteMatrix = hermiteMatrix.T

			JitterMatrix[:,0] = (1.0/np.sqrt(2.0))*(-1.0*hermiteMatrix[:,1])/MeanBeta
			for i in range(1,self.MaxCoeff):
				JitterMatrix[:,i] = (1.0/np.sqrt(2.0))*(np.sqrt(1.0*i)*hermiteMatrix[:,i-1] - np.sqrt(1.0*(i+1))*hermiteMatrix[:,i+1])/MeanBeta



			self.InterpBasis[t]  = np.copy(hermiteMatrix[:,:self.MaxCoeff])
			self.InterpJitterMatrix[t] = np.copy(JitterMatrix)

			InterpFShapeMatrix[t]  = np.copy(np.fft.rfft(hermiteMatrix[:,:self.MaxCoeff], axis=0))
			InterpFJitterMatrix[t] = np.copy(np.fft.rfft(JitterMatrix, axis=0))


		threshold = 10.0**-10
		upperindex=1
		while(np.max(np.abs(InterpFShapeMatrix[0,upperindex:,:])) > threshold):
			upperindex += 5
			if(upperindex >= lenRFFT):
				upperindex = lenRFFT-1
				break
			print "upper index is:", upperindex,np.max(np.abs(InterpFShapeMatrix[0,upperindex:,:]))
		#InterpShapeMatrix = np.array(InterpShapeMatrix)
		#InterpJitterMatrix = np.array(InterpJitterMatrix)
		print("\nFinished Computing Interpolated Profiles")


		self.InterpFBasis = InterpFShapeMatrix[:,1:upperindex,:]
		self.InterpFJitterMatrix = InterpFJitterMatrix[:,1:upperindex,:]
		self.InterpolatedTime  = InterpolatedTime

		Fdata =  np.fft.rfft(self.ProfileData, axis=1)[:,1:upperindex]

		self.NFBasis = upperindex - 1
		self.ProfileFData = np.zeros([self.NToAs, 2*self.NFBasis])
		self.ProfileFData[:, :self.NFBasis] = np.real(Fdata)
		self.ProfileFData[:, self.NFBasis:] = np.imag(Fdata)
		

	def getInitialPhase(self, doplot = True):
	

		print "Getting initial fit to phase using full data"


		self.doplot = False

		phases=[]
		likes=[]
		minphase = 0.0
		maxphase = 1.0
		for loop in range(4):
			stepsize = (maxphase-minphase)/100
			mlike = -np.inf
			mphase=0
			for p in range(100):
				self.update_progress(np.float64(loop*100 + p)/400.0)
				phase = minphase + p*stepsize
				like = self.PhaseLike(np.ones(1)*phase)
				phases.append(phase)
				likes.append(like)
				if(like > mlike):
					mlike = like
					mphase = np.ones(1)*phase

	
			minphase = mphase - stepsize
			maxphase = mphase + stepsize

		if(doplot == True):
			plt.scatter(phases, likes)
			plt.xlabel('Phase')
			plt.ylabel('Log-Likelihood')
			plt.show()

		self.MeanPhase = mphase

		print "\n"

		self.getShapeletStepSize = True
		self.hess = self.PhaseLike(np.ones(1)*mphase)
		self.getShapeletStepSize = False

		#self.doplot=True
		#self.PhaseLike(ML)
		



	#@profile
	def PhaseLike(self, x):
	    

		pcount = 0
		phase = x[pcount]*self.ReferencePeriod
		pcount += 1

		loglike = 0

		stepsize=np.zeros([self.MaxCoeff - 1, self.EvoNPoly+1])

		xS = self.ShiftedBinTimes[:,0]-phase

		xS = ( xS + self.ReferencePeriod/2) % (self.ReferencePeriod ) - self.ReferencePeriod/2

		InterpBins = (xS%(self.ReferencePeriod/self.Nbins[:])/self.InterpolatedTime).astype(int)
		WBTs = xS-self.InterpolatedTime*InterpBins
		RollBins=(np.round(WBTs/(self.ReferencePeriod/self.Nbins[:]))).astype(np.int)


		SmallS=[np.dot(self.InterpFBasis[InterpBins[i]], np.sum(((self.psr.freqs[i] - self.EvoRefFreq)/1000.0)**np.arange(0,self.EvoNPoly+1)*self.MLShapeCoeff[:self.MaxCoeff], axis=1)) for i in range(len(RollBins))]

		if(self.NScatterEpochs > 0):
			for i in range(self.NToAs):
				ScatterScale = (self.psr.freqs[i]*10.0**6)**4/10.0**(9.0*4.0)
				STime = 10.0**self.MeanScatter/ScatterScale
				ScatterVec = self.ConvolveExp(np.linspace(1, self.NFBasis, self.NFBasis)/self.ReferencePeriod, STime)
				SmallS[i] *= ScatterVec

		s=np.zeros([self.NToAs, self.NFBasis+1])+0j
		s[:,1:] = SmallS

		s=np.fft.irfft(s, n=self.Nbins[0], axis=1)
		s=[np.roll(s[i], -RollBins[i]) for i in range(len(RollBins))]


		#Rescale
		s = [s[i]/(np.dot(s[i],s[i])/self.Nbins[i]) for i in range(self.NToAs)]

		for i in range(self.NToAs):

			#Make design matrix.  Two components: baseline and profile shape.

			M=np.ones([2,self.Nbins[i]])
			M[1] = s[i]


			pnoise = self.ProfileInfo[i][6]

			MNM = np.dot(M, M.T)      
			MNM /= (pnoise*pnoise)

			#Invert design matrix. 2x2 so just do it numerically


			detMNM = MNM[0][0]*MNM[1][1] - MNM[1][0]*MNM[0][1]
			InvMNM = np.zeros([2,2])
			InvMNM[0][0] = MNM[1][1]/detMNM
			InvMNM[1][1] = MNM[0][0]/detMNM
			InvMNM[0][1] = -1*MNM[0][1]/detMNM
			InvMNM[1][0] = -1*MNM[1][0]/detMNM

			logdetMNM = np.log(detMNM)
			    
			#Now get dNM and solve for likelihood.
			    
			    
			dNM = np.dot(self.ProfileData[i], M.T)/(pnoise*pnoise)


			dNMMNM = np.dot(dNM.T, InvMNM)
			MarginLike = np.dot(dNMMNM, dNM)

			profilelike = -0.5*(logdetMNM - MarginLike)
			loglike += profilelike


			if(self.getShapeletStepSize == True):
				amp = dNMMNM[1]
				for j in range(self.MaxCoeff - 1):
					EvoFac = (((self.psr.freqs[i]-self.EvoRefFreq)/1000)**np.arange(0,self.EvoNPoly+1))**2
					BVec = amp*np.roll(self.InterpBasis[InterpBins[i]][:,j], -RollBins[i])
					stepsize[j] += EvoFac*np.dot(BVec, BVec)/self.ProfileInfo[i][6]/self.ProfileInfo[i][6]


			if(self.doplot == True):
			    baseline=dNMMNM[0]
			    amp = dNMMNM[1]
			    noise = np.std(self.ProfileData[i] - baseline - amp*s[i])
			    print i, amp, baseline, noise
			    plt.plot(np.linspace(0,1,self.Nbins[i]), self.ProfileData[i])
			    plt.plot(np.linspace(0,1,self.Nbins[i]),baseline+s[i]*amp)
			    plt.show()
			    plt.plot(np.linspace(0,1,self.Nbins[i]),self.ProfileData[i]-(baseline+s[i]*amp))
			    plt.show()

		if(self.getShapeletStepSize == True):
			for j in range(self.MaxCoeff - 1):
				print "step size ", j,  stepsize[j], 1.0/np.sqrt(stepsize[j])
			return 1.0/np.sqrt(stepsize)
	
		return loglike


	#@profile
	#Shifted=np.fft.irfft(np.fft.rfft(np.float64(ZeroExVec))*np.exp(1*2*np.pi*231*rfftfreqs*1j))

	def MarginLogLike(self, x):
	    


		pcount = 0
		phase=x[0]*self.ReferencePeriod#self.MeanPhase*self.ReferencePeriod
		phasePrior = -0.5*(phase-self.MeanPhase)*(phase-self.MeanPhase)/self.PhasePrior/self.PhasePrior
	
		pcount += 1

		NCoeff = self.MaxCoeff-1
		#pcount += 1


		ShapeAmps=np.zeros([self.MaxCoeff, self.EvoNPoly+1])
		ShapeAmps[0][0] = 1
		ShapeAmps[1:]=x[pcount:pcount+(self.MaxCoeff-1)*(self.EvoNPoly+1)].reshape([(self.MaxCoeff-1),(self.EvoNPoly+1)])


		pcount += (self.MaxCoeff-1)*(self.EvoNPoly+1)

		TimingParameters=x[pcount:pcount+self.numTime]
		pcount += self.numTime

		loglike = 0

		TimeSignal = np.dot(self.designMatrix, TimingParameters)

		xS = self.ShiftedBinTimes[:,0]-phase

		if(self.numTime>0):
			xS -= TimeSignal

		xS = ( xS + self.ReferencePeriod/2) % (self.ReferencePeriod ) - self.ReferencePeriod/2

		InterpBins = (xS%(self.ReferencePeriod/self.Nbins[:])/self.InterpolatedTime).astype(int)
		WBTs = xS-self.InterpolatedTime*InterpBins
		RollBins=(np.round(WBTs/(self.ReferencePeriod/self.Nbins[:]))).astype(np.int)





		s=[np.roll(np.dot(self.InterpBasis[InterpBins[i]][:,:NCoeff+1], np.sum(((self.psr.freqs[i] - self.EvoRefFreq)/1000.0)**np.arange(0,self.EvoNPoly+1)*ShapeAmps, axis=1)), -RollBins[i]) for i in range(len(RollBins))]
		s = [s[i] - np.sum(s[i])/self.Nbins[i] for i in range(self.NToAs)]	
		s = [s[i]/(np.dot(s[i],s[i])/self.Nbins[i]) for i in range(self.NToAs)]




		s=[np.dot(self.InterpFBasis[InterpBins[i]], np.sum(((self.psr.freqs[i] - self.EvoRefFreq)/1000.0)**np.arange(0,self.EvoNPoly+1)*self.MLShapeCoeff, axis=1)) for i in range(len(RollBins))]
		for i in range(len(RollBins)):
			s[i][0]=0
		s=np.fft.irfft(s, n=self.Nbins[0], axis=1)
		s=[np.roll(s[i], -RollBins[i]) for i in range(len(RollBins))]


		#Rescale
		s = [s[i]/(np.dot(s[i],s[i])/self.Nbins[i]) for i in range(self.NToAs)]





		for i in range(self.NToAs):


			'''Make design matrix.  Two components: baseline and profile shape.'''

			M=np.ones([2,self.Nbins[i]])
			M[1] = s[i]


			pnoise = self.ProfileInfo[i][6]

			MNM = np.dot(M, M.T)      
			MNM /= (pnoise*pnoise)

			'''Invert design matrix. 2x2 so just do it numerically'''


			detMNM = MNM[0][0]*MNM[1][1] - MNM[1][0]*MNM[0][1]
			InvMNM = np.zeros([2,2])
			InvMNM[0][0] = MNM[1][1]/detMNM
			InvMNM[1][1] = MNM[0][0]/detMNM
			InvMNM[0][1] = -1*MNM[0][1]/detMNM
			InvMNM[1][0] = -1*MNM[1][0]/detMNM

			logdetMNM = np.log(detMNM)
			    
			'''Now get dNM and solve for likelihood.'''
			    
			    
			dNM = np.dot(self.ProfileData[i], M.T)/(pnoise*pnoise)


			dNMMNM = np.dot(dNM.T, InvMNM)
			MarginLike = np.dot(dNMMNM, dNM)

			profilelike = -0.5*(logdetMNM - MarginLike)
			loglike += profilelike

			if(self.doplot == True):
			    baseline=dNMMNM[0]
			    amp = dNMMNM[1]
			    noise = np.std(self.ProfileData[i] - baseline - amp*s)
			    print i, amp, baseline, noise
			    plt.plot(np.linspace(0,1,self.Nbins[i]), self.ProfileData[i])
			    plt.plot(np.linspace(0,1,self.Nbins[i]),baseline+s[i]*amp)
			    plt.show()
			    plt.plot(np.linspace(0,1,self.Nbins[i]),self.ProfileData[i]-(baseline+s[i]*amp))
			    plt.show()

		return loglike+phasePrior

	#@profile	
	def FFTMarginLogLike(self, x):
	    


		pcount = 0
		phase=x[0]*self.ReferencePeriod
		phasePrior = -0.5*(phase-self.MeanPhase)*(phase-self.MeanPhase)/self.PhasePrior/self.PhasePrior

		pcount += 1

		NCoeff = self.MaxCoeff-1
		#pcount += 1


		ShapeAmps=np.zeros([self.MaxCoeff, self.EvoNPoly+1])
		ShapeAmps[0][0] = 1
		ShapeAmps[1:]=x[pcount:pcount+(self.MaxCoeff-1)*(self.EvoNPoly+1)].reshape([(self.MaxCoeff-1),(self.EvoNPoly+1)])


		pcount += (self.MaxCoeff-1)*(self.EvoNPoly+1)

		TimingParameters=x[pcount:pcount+self.numTime]
		pcount += self.numTime

		ScatteringParameters = 10.0**x[pcount:pcount+self.NScatterEpochs]
		pcount += self.NScatterEpochs


		loglike = 0

		TimeSignal = np.dot(self.designMatrix, TimingParameters)

		xS = self.ShiftedBinTimes[:,0]-phase

		if(self.numTime>0):
			xS -= TimeSignal

		xS = ( xS + self.ReferencePeriod/2) % (self.ReferencePeriod ) - self.ReferencePeriod/2

		InterpBins = (xS%(self.ReferencePeriod/self.Nbins[:])/self.InterpolatedTime).astype(int)
		WBTs = xS-self.InterpolatedTime*InterpBins
		RollBins=(np.round(WBTs/(self.ReferencePeriod/self.Nbins[:]))).astype(np.int)


		#s = [np.dot(self.InterpFBasis[InterpBins[i]], np.sum(((self.psr.freqs[i] - self.EvoRefFreq)/1000.0)**np.arange(0,self.EvoNPoly+1)*ShapeAmps, axis=1)) for i in range(len(RollBins))]
		s = np.sum([np.dot(self.InterpFBasis[InterpBins], ShapeAmps[:,i])*(((self.psr.freqs - self.EvoRefFreq)/1000.0)**i).reshape(self.NToAs,1) for i in range(self.EvoNPoly+1)], axis=0)


		for i in range(self.NToAs):

			rfftfreqs=np.linspace(1,self.NFBasis,self.NFBasis)/self.Nbins[i]

			pnoise = self.ProfileInfo[i,6]*np.sqrt(self.Nbins[i])/np.sqrt(2)

			rollVec = np.exp(2*np.pi*RollBins[i]*rfftfreqs*1j)
			rollS1 = s[i]*rollVec

			if(self.NScatterEpochs > 0):
				ScatterScale = self.psr.ssbfreqs()[i]**4/10.0**(9.0*4.0)
				STime = np.sum(ScatteringParameters[self.ScatterInfo[i]])/ScatterScale
				ScatterVec = self.ConvolveExp(rfftfreqs*self.Nbins[i]/self.ReferencePeriod, STime)

				rollS1 *= ScatterVec

			FS = np.zeros(2*self.NFBasis)
			FS[:self.NFBasis] = np.real(rollS1)
			FS[self.NFBasis:] = np.imag(rollS1)

			FS /= np.sqrt(np.dot(FS,FS)/(2*self.NFBasis))

			MNM = np.dot(FS, FS)/(pnoise*pnoise)
			detMNM = MNM
			logdetMNM = np.log(detMNM)

			InvMNM = 1.0/MNM

			dNM = np.dot(self.ProfileFData[i], FS)/(pnoise*pnoise)
			dNMMNM = dNM*InvMNM

			MarginLike = dNMMNM*dNM

			profilelike = -0.5*(logdetMNM - MarginLike)
			loglike += profilelike     


			if(self.doplot == True):
			    baseline=dNMMNM[0]
			    amp = dNMMNM[1]
			    noise = np.std(self.ProfileData[i] - baseline - amp*s)
			    print i, amp, baseline, noise
			    plt.plot(np.linspace(0,1,self.Nbins[i]), self.ProfileData[i])
			    plt.plot(np.linspace(0,1,self.Nbins[i]),baseline+s[i]*amp)
			    plt.show()
			    plt.plot(np.linspace(0,1,self.Nbins[i]),self.ProfileData[i]-(baseline+s[i]*amp))
			    plt.show()

		return loglike+phasePrior

	def calculateHessian(self,x):

		pcount = 0
		phase=x[0]*self.ReferencePeriod
		pcount += 1

		NCoeff = self.MaxCoeff-1
		#pcount += 1


		ShapeAmps=np.zeros([self.MaxCoeff, self.EvoNPoly+1])
		ShapeAmps[0][0] = 1
		ShapeAmps[1:]=x[pcount:pcount+(self.MaxCoeff-1)*(self.EvoNPoly+1)].reshape([(self.MaxCoeff-1),(self.EvoNPoly+1)])


		pcount += (self.MaxCoeff-1)*(self.EvoNPoly+1)

		TimingParameters=x[pcount:pcount+self.numTime]
		pcount += self.numTime

		loglike = 0

		TimeSignal = np.dot(self.designMatrix, TimingParameters)

		xS = self.ShiftedBinTimes[:,0]-phase

		if(self.numTime>0):
			xS -= TimeSignal

		xS = ( xS + self.ReferencePeriod/2) % (self.ReferencePeriod ) - self.ReferencePeriod/2

		InterpBins = (xS%(self.ReferencePeriod/self.Nbins[:])/self.InterpolatedTime).astype(int)
		WBTs = xS-self.InterpolatedTime*InterpBins
		RollBins=(np.round(WBTs/(self.ReferencePeriod/self.Nbins[:]))).astype(np.int)


		#Multiply and shift out the shapelet model

		s=[np.roll(np.dot(self.InterpBasis[InterpBins[i]][:,:NCoeff+1], np.sum(((self.psr.freqs[i] - self.EvoRefFreq)/1000.0)**np.arange(0,self.EvoNPoly+1)*ShapeAmps, axis=1)), -RollBins[i]) for i in range(len(RollBins))]

		j=[np.roll(np.dot(self.InterpJitterMatrix[InterpBins[i]][:,:NCoeff+1], np.sum(((self.psr.freqs[i] - self.EvoRefFreq)/1000.0)**np.arange(0,self.EvoNPoly+1)*ShapeAmps, axis=1)), -RollBins[i]) for i in range(len(RollBins))]


		FFTS = np.sum([np.dot(self.InterpFBasis[InterpBins], ShapeAmps[:,i])*(((self.psr.freqs - self.EvoRefFreq)/1000.0)**i).reshape(self.NToAs,1) for i in range(self.EvoNPoly+1)], axis=0)
		FFTS = [np.exp(2*np.pi*RollBins[i]*(np.linspace(1,self.NFBasis,self.NFBasis)/self.Nbins[i])*1j)*FFTS[i] for i in range(self.NToAs)]


		HessSize = self.n_params
		Hessian = np.zeros([HessSize,HessSize])
		LinearSize = 1 + (self.MaxCoeff-1)*(self.EvoNPoly+1) + self.numTime

		MLAmps = np.zeros(self.NToAs)
		for i in range(self.NToAs):


			smean = np.sum(s[i])/self.Nbins[i] 
			s[i] = s[i]-smean
			j[i] = j[i]-smean

			sstd = np.dot(s[i],s[i])/self.Nbins[i]
			s[i]=s[i]/np.sqrt(sstd)
			j[i]=j[i]/np.sqrt(sstd)

			M=np.ones([2,self.Nbins[i]])
			M[1] = s[i]


			pnoise = self.ProfileInfo[i][6]

			MNM = np.dot(M, M.T)      
			MNM /= (pnoise*pnoise)


			detMNM = MNM[0][0]*MNM[1][1] - MNM[1][0]*MNM[0][1]
			InvMNM = np.zeros([2,2])
			InvMNM[0][0] = MNM[1][1]/detMNM
			InvMNM[1][1] = MNM[0][0]/detMNM
			InvMNM[0][1] = -1*MNM[0][1]/detMNM
			InvMNM[1][0] = -1*MNM[1][0]/detMNM


			    
			'''Now get dNM and solve for likelihood.'''
			    
			    
			dNM = np.dot(self.ProfileData[i], M.T)/(pnoise*pnoise)

			dNMMNM = np.dot(dNM.T, InvMNM)

			baseline=dNMMNM[0]
			MLAmp = dNMMNM[1]
			MLSigma = pnoise


			MLAmps[i] = MLAmp

			HessMatrix = np.zeros([LinearSize, self.Nbins[i]])


			#Phase First
			PhaseScale = MLAmp/MLSigma

			pcount = 0
			HessMatrix[pcount,:] = PhaseScale*j[i]*self.ReferencePeriod
			pcount += 1


			#Hessian for Shapelet parameters
			fvals = ((self.psr.freqs[i] - self.EvoRefFreq)/1000.0)**np.arange(0,self.EvoNPoly+1)

			for c in range(1, self.MaxCoeff):
				for p in range(self.EvoNPoly+1):
					HessMatrix[pcount,:] = fvals[p]*np.roll(self.InterpBasis[InterpBins[i]][:,c], -RollBins[i])*MLAmp/MLSigma
					pcount += 1

			#Hessian for Timing Model

			for c in range(self.numTime):
				HessMatrix[pcount,:] = j[i]*PhaseScale*self.designMatrix[i,c]
				pcount += 1


			OneHess = np.dot(HessMatrix, HessMatrix.T)
			Hessian[:LinearSize, :LinearSize] += OneHess
		


			for c in range(self.NScatterEpochs):
				if(c in self.ScatterInfo[i]):

					tau = 10.0**x[-self.NScatterEpochs+c]
					f = np.linspace(1,self.NFBasis,self.NFBasis)/self.ReferencePeriod
					w = 2.0*np.pi*f
					ScatterScale = 1.0/(self.psr.ssbfreqs()[i]**4/10.0**(9.0*4.0))

					Conv = self.ConvolveExp(f, tau*ScatterScale)

					ConvVec = np.zeros(2*self.NFBasis)
					ConvVec[:self.NFBasis] = np.real(Conv)
					ConvVec[self.NFBasis:] = np.imag(Conv)


					PVec = np.zeros(2*self.NFBasis)
					PVec[:self.NFBasis] = MLAmps[i]*np.real(FFTS[i])
					PVec[self.NFBasis:] = MLAmps[i]*np.imag(FFTS[i])

					pnoise = self.ProfileInfo[i,6]*np.sqrt(self.Nbins[i])/np.sqrt(2)

					HessDenom = 1.0/(1.0 + tau**2*w**2*ScatterScale**2)**3
					GradDenom = 1.0/(1.0 + tau**2*w**2*ScatterScale**2)**2


					rHess2 = -(4*tau**2*ScatterScale**2*w**2*(tau**2*ScatterScale**2*w**2 - 1)*np.log(10.0)**2)*HessDenom*PVec[:self.NFBasis]
					rGrad2 = 2*tau**2*ScatterScale**2*w**2*np.log(10.0)*GradDenom*PVec[:self.NFBasis]
					rFunc2 = (self.ProfileFData[i][:self.NFBasis] - PVec[:self.NFBasis]*np.real(Conv))

					FullRealHess = -1*(rHess2*rFunc2 + rGrad2**2)*(1.0/pnoise**2)

					iHess2 = tau*ScatterScale*w*(1+tau**2*ScatterScale**2*w**2*(tau**2*ScatterScale**2*w**2 - 6))*np.log(10.0)**2*HessDenom*PVec[self.NFBasis:]
					iGrad2 = -tau*ScatterScale*w*(tau**2*ScatterScale**2*w**2 - 1)*np.log(10.0)*GradDenom*PVec[self.NFBasis:]
					iFunc2 = (self.ProfileFData[i][self.NFBasis:] - PVec[self.NFBasis:]*np.imag(Conv))

					FullImagHess = -1*(iHess2*iFunc2 + iGrad2**2)*(1.0/pnoise**2)
				

					profhess = np.zeros(2*self.NFBasis)
					profhess[:self.NFBasis] = FullRealHess
					profhess[self.NFBasis:] = FullImagHess

					profgrad = np.zeros(2*self.NFBasis)
					profgrad[:self.NFBasis] = -0.5*rGrad2*(1.0/pnoise**2)
					profgrad[self.NFBasis:] = -0.5*iGrad2*(1.0/pnoise**2)

					Hessian[pcount+c,pcount+c] += np.sum(profhess)
					print c, i, Hessian[pcount+c,pcount+c]
					pcount += 1


		self.hess = Hessian


	def calculateFFTHessian(self,x):

		pcount = 0
		phase=x[0]*self.ReferencePeriod
		pcount += 1

		NCoeff = self.MaxCoeff-1
		#pcount += 1


		ShapeAmps=np.zeros([self.MaxCoeff, self.EvoNPoly+1])
		ShapeAmps[0][0] = 1
		ShapeAmps[1:]=x[pcount:pcount+(self.MaxCoeff-1)*(self.EvoNPoly+1)].reshape([(self.MaxCoeff-1),(self.EvoNPoly+1)])


		pcount += (self.MaxCoeff-1)*(self.EvoNPoly+1)

		TimingParameters=x[pcount:pcount+self.numTime]
		pcount += self.numTime

		ScatteringParameters = 10.0**x[pcount:pcount+self.NScatterEpochs]
		pcount += self.NScatterEpochs

		loglike = 0

		TimeSignal = np.dot(self.designMatrix, TimingParameters)

		xS = self.ShiftedBinTimes[:,0]-phase

		if(self.numTime>0):
			xS -= TimeSignal

		xS = ( xS + self.ReferencePeriod/2) % (self.ReferencePeriod ) - self.ReferencePeriod/2

		InterpBins = (xS%(self.ReferencePeriod/self.Nbins[:])/self.InterpolatedTime).astype(int)
		WBTs = xS-self.InterpolatedTime*InterpBins
		RollBins=(np.round(WBTs/(self.ReferencePeriod/self.Nbins[:]))).astype(np.int)


		#Multiply and shift out the shapelet model

		s=[np.roll(np.dot(self.InterpBasis[InterpBins[i]][:,:NCoeff+1], np.sum(((self.psr.freqs[i] - self.EvoRefFreq)/1000.0)**np.arange(0,self.EvoNPoly+1)*ShapeAmps, axis=1)), -RollBins[i]) for i in range(len(RollBins))]

		j=[np.roll(np.dot(self.InterpJitterMatrix[InterpBins[i]][:,:NCoeff+1], np.sum(((self.psr.freqs[i] - self.EvoRefFreq)/1000.0)**np.arange(0,self.EvoNPoly+1)*ShapeAmps, axis=1)), -RollBins[i]) for i in range(len(RollBins))]


		FFTS = np.sum([np.dot(self.InterpFBasis[InterpBins], ShapeAmps[:,i])*(((self.psr.freqs - self.EvoRefFreq)/1000.0)**i).reshape(self.NToAs,1) for i in range(self.EvoNPoly+1)], axis=0)
		FFTJ = np.fft.rfft(j, axis=1)[:,1:self.NFBasis+1]

		HessSize = self.n_params
		Hessian = np.zeros([HessSize,HessSize])
		LinearSize = 1 + (self.MaxCoeff-1)*(self.EvoNPoly+1) + self.numTime

		for i in range(self.NToAs):

			rfftfreqs=np.linspace(1,self.NFBasis,self.NFBasis)/self.Nbins[i]

			RollVec = np.exp(2*np.pi*RollBins[i]*rfftfreqs*1j)
			FFTS[i] = FFTS[i]*RollVec
			OneProf = FFTS[i]
			FFTJ[i] = FFTJ[i]#*RollVec

			if(self.NScatterEpochs > 0):

				ScatterScale = self.psr.ssbfreqs()[i]**4/10.0**(9.0*4.0)
				STime = np.sum(ScatteringParameters[self.ScatterInfo[i]])/ScatterScale
				ScatterVec = self.ConvolveExp(rfftfreqs*self.Nbins[i]/self.ReferencePeriod, STime)

				OneProf = OneProf*ScatterVec
				FFTJ[i] = FFTJ[i]*ScatterVec




			FS = np.zeros(2*self.NFBasis)
			FS[:self.NFBasis] = np.real(OneProf)
			FS[self.NFBasis:] = np.imag(OneProf)

			FJ = np.zeros(2*self.NFBasis)
			FJ[:self.NFBasis] = np.real(FFTJ[i])
			FJ[self.NFBasis:] = np.imag(FFTJ[i])

			FSdot = np.sqrt(np.dot(FS,FS)/(2*self.NFBasis))

			FS /= FSdot
			FJ /= FSdot



			pnoise = self.ProfileInfo[i,6]*np.sqrt(self.Nbins[i])/np.sqrt(2)

			MNM = np.dot(FS, FS)/(pnoise*pnoise)
			InvMNM = 1.0/MNM

			dNM = np.dot(self.ProfileFData[i], FS)/(pnoise*pnoise)
			dNMMNM = dNM*InvMNM

			MLAmp = dNMMNM
			MLSigma = pnoise


			HessMatrix = np.zeros([LinearSize, 2*self.NFBasis])

			print "ML Amp/Noise: ", i, MLAmp, MLSigma
			#Phase First
			PhaseScale = MLAmp/MLSigma

			pcount = 0
			HessMatrix[pcount,:] = PhaseScale*FJ*self.ReferencePeriod
			pcount += 1


			#Hessian for Shapelet parameters
			fvals = ((self.psr.freqs[i] - self.EvoRefFreq)/1000.0)**np.arange(0,self.EvoNPoly+1)

			OriginalBasis = (self.InterpFBasis[InterpBins[i]].T*RollVec).T
			if(self.NScatterEpochs > 0):
				OriginalBasis = (OriginalBasis.T*ScatterVec).T

			OneBasis = np.zeros([2*self.NFBasis, self.MaxCoeff])
			OneBasis[:self.NFBasis] = np.real(OriginalBasis)
			OneBasis[self.NFBasis:] = np.imag(OriginalBasis)


			for c in range(1, self.MaxCoeff):
				for p in range(self.EvoNPoly+1):
					HessMatrix[pcount,:] = fvals[p]*OneBasis[:,c]*MLAmp/MLSigma
					pcount += 1

			#Hessian for Timing Model

			for c in range(self.numTime):
				HessMatrix[pcount,:] = FJ*PhaseScale*self.designMatrix[i,c]
				pcount += 1


			OneHess = np.dot(HessMatrix, HessMatrix.T)
			Hessian[:LinearSize, :LinearSize] += OneHess
			'''
			for c in range(LinearSize):
				for d in range(LinearSize):
					print "Lin Hess:", c, d, OneHess[c,d]

			'''

			for c in range(self.NScatterEpochs):
				if(c in self.ScatterInfo[i]):

					tau = ScatteringParameters[c]
					f = np.linspace(1,self.NFBasis,self.NFBasis)/self.ReferencePeriod
					w = 2.0*np.pi*f
					ISS = 1.0/(self.psr.ssbfreqs()[i]**4/10.0**(9.0*4.0))

					Conv = self.ConvolveExp(f, tau*ISS)
					#MLProf = MLAmp*FFTS[i]#/FSdot
					#ConvProf = Conv*MLProf


					RConv = np.real(Conv)
					IConv = np.imag(Conv)


					#PVec = np.zeros(2*self.NFBasis)
					#PVec[:self.NFBasis] = MLAmp*np.real(FFTS[i])/FSdot
					#PVec[self.NFBasis:] = MLAmp*np.imag(FFTS[i])/FSdot

					RProf = MLAmp*np.real(FFTS[i])/FSdot
					IProf = MLAmp*np.imag(FFTS[i])/FSdot

					pnoise = self.ProfileInfo[i,6]*np.sqrt(self.Nbins[i])/np.sqrt(2)
					'''
					dval=self.ProfileFData[i][0]
					prval=PVec[:self.NFBasis][0]
					pival=PVec[self.NFBasis:][0]
					wval=w[0]
					sval=ISS
					tval=np.log10(tau)
					oval = pnoise
					dval, prval, pival, wval, sval, tval,oval

					dival=self.ProfileFData[i][self.NFBasis]
					prval=PVec[:self.NFBasis][0]
					pival=PVec[self.NFBasis:][0]
					wval=w[0]
					sval=ISS
					tval=np.log10(tau)
					oval = pnoise
					dival, prval, pival, wval, sval, tval,oval
					'''
					HessDenom = 1.0/(1.0 + tau**2*w**2*ISS**2)**3
					GradDenom = 1.0/(1.0 + tau**2*w**2*ISS**2)**2

					Reaself = (self.ProfileFData[i][:self.NFBasis] - RProf*RConv + IProf*IConv)
					RealGrad = 2*tau**2*ISS**2*w**2*np.log(10.0)*GradDenom*RProf + tau*ISS*w*(tau**2*ISS**2*w**2 - 1)*np.log(10.0)*GradDenom*IProf
					RealHess = -(4*tau**2*ISS**2*w**2*(tau**2*ISS**2*w**2 - 1)*np.log(10.0)**2)*HessDenom*RProf - tau*ISS*w*(1+tau**2*ISS**2*w**2*(tau**2*ISS**2*w**2 - 6))*np.log(10.0)**2*HessDenom*IProf

					FullRealHess = 1*(RealHess*Reaself + RealGrad**2)*(1.0/pnoise**2)

					ImagFunc = (self.ProfileFData[i][self.NFBasis:] - RProf*IConv - IProf*RConv)
					ImagGrad = 2*tau**2*ISS**2*w**2*np.log(10.0)*GradDenom*IProf - tau*ISS*w*(tau**2*ISS**2*w**2 - 1)*np.log(10.0)*GradDenom*RProf
					ImagHess = -(4*tau**2*ISS**2*w**2*(tau**2*ISS**2*w**2 - 1)*np.log(10.0)**2)*HessDenom*IProf + tau*ISS*w*(1+tau**2*ISS**2*w**2*(tau**2*ISS**2*w**2 - 6))*np.log(10.0)**2*HessDenom*RProf



					FullImagHess = 1*(ImagHess*ImagFunc + ImagGrad**2)*(1.0/pnoise**2)


					profhess = np.zeros(2*self.NFBasis)
					profhess[:self.NFBasis] = FullRealHess
					profhess[self.NFBasis:] = FullImagHess

					profgrad = np.zeros(2*self.NFBasis)
					profgrad[:self.NFBasis] = RealGrad*(1.0/pnoise)
					profgrad[self.NFBasis:] = ImagGrad*(1.0/pnoise)

					LinearScatterCross = np.dot(HessMatrix, profgrad)

					
					

					Hessian[pcount+c,pcount+c] += np.sum(profhess)
					Hessian[:LinearSize, pcount+c] += -LinearScatterCross
					Hessian[pcount+c, :LinearSize] += -LinearScatterCross
					
					pcount += 1


		self.hess = Hessian


	def calculateShapePhaseCov(self,x):

		pcount = 0
		phase=x[0]*self.ReferencePeriod
		pcount += 1

		NCoeff = self.MaxCoeff-1
		#pcount += 1


		ShapeAmps=np.zeros([self.MaxCoeff, self.EvoNPoly+1])
		ShapeAmps[0][0] = 1
		ShapeAmps[1:]=x[pcount:pcount+(self.MaxCoeff-1)*(self.EvoNPoly+1)].reshape([(self.MaxCoeff-1),(self.EvoNPoly+1)])


		pcount += (self.MaxCoeff-1)*(self.EvoNPoly+1)

		TimingParameters=x[pcount:pcount+self.numTime]
		pcount += self.numTime

		loglike = 0

		TimeSignal = np.dot(self.designMatrix, TimingParameters)

		xS = self.ShiftedBinTimes[:,0]-phase

		if(self.numTime>0):
			xS -= TimeSignal

		xS = ( xS + self.ReferencePeriod/2) % (self.ReferencePeriod ) - self.ReferencePeriod/2

		InterpBins = (xS%(self.ReferencePeriod/self.Nbins[:])/self.InterpolatedTime).astype(int)
		WBTs = xS-self.InterpolatedTime*InterpBins
		RollBins=(np.round(WBTs/(self.ReferencePeriod/self.Nbins[:]))).astype(np.int)


		#Multiply and shift out the shapelet model

		s=[np.roll(np.dot(self.InterpBasis[InterpBins[i]][:,:NCoeff+1], np.sum(((self.psr.freqs[i] - self.EvoRefFreq)/1000.0)**np.arange(0,self.EvoNPoly+1)*ShapeAmps, axis=1)), -RollBins[i]) for i in range(len(RollBins))]

		j=[np.roll(np.dot(self.InterpJitterMatrix[InterpBins[i]][:,:NCoeff+1], np.sum(((self.psr.freqs[i] - self.EvoRefFreq)/1000.0)**np.arange(0,self.EvoNPoly+1)*ShapeAmps, axis=1)), -RollBins[i]) for i in range(len(RollBins))]



		HessSize = 1 +(self.MaxCoeff-1)
		Hessian = np.zeros([HessSize,HessSize])

		for i in range(self.NToAs):


			smean = np.sum(s[i])/self.Nbins[i] 
			s[i] = s[i]-smean
			j[i] = j[i]-smean

			sstd = np.dot(s[i],s[i])/self.Nbins[i]
			s[i]=s[i]/np.sqrt(sstd)
			j[i]=j[i]/np.sqrt(sstd)

			M=np.ones([2,self.Nbins[i]])
			M[1] = s[i]


			pnoise = self.ProfileInfo[i][6]

			MNM = np.dot(M, M.T)      
			MNM /= (pnoise*pnoise)


			detMNM = MNM[0][0]*MNM[1][1] - MNM[1][0]*MNM[0][1]
			InvMNM = np.zeros([2,2])
			InvMNM[0][0] = MNM[1][1]/detMNM
			InvMNM[1][1] = MNM[0][0]/detMNM
			InvMNM[0][1] = -1*MNM[0][1]/detMNM
			InvMNM[1][0] = -1*MNM[1][0]/detMNM


			    
			'''Now get dNM and solve for likelihood.'''
			    
			    
			dNM = np.dot(self.ProfileData[i], M.T)/(pnoise*pnoise)

			dNMMNM = np.dot(dNM.T, InvMNM)

			baseline=dNMMNM[0]
			MLAmp = dNMMNM[1]
			MLSigma = pnoise

			HessMatrix = np.zeros([HessSize, self.Nbins[i]])


			#Phase First
			PhaseScale = MLAmp/MLSigma

			pcount = 0
			HessMatrix[pcount,:] = PhaseScale*j[i]*self.ReferencePeriod
			pcount += 1

			fvals = ((self.psr.freqs[i] - self.EvoRefFreq)/1000.0)**np.arange(0,self.EvoNPoly+1)

			for c in range(1, self.MaxCoeff):
				HessMatrix[pcount,:] = fvals[0]*np.roll(self.InterpBasis[InterpBins[i]][:,c], -RollBins[i])*MLAmp/MLSigma
				pcount += 1

			OneHess = np.dot(HessMatrix, HessMatrix.T)
			Hessian += OneHess

		self.ShapePhaseCov = Hessian
	


	#Jump proposal for the timing model parameters
	def TimeJump(self, x, iteration, beta):


		q=x.copy()
		y=np.dot(self.FisherU.T,x[-self.numTime:])
		ind = np.unique(np.random.randint(0,self.numTime,np.random.randint(0,self.numTime,1)[0]))
		ran=np.random.standard_normal(self.numTime)
		y[ind]=y[ind]+ran[ind]#/np.sqrt(FisherS[ind])

		newpars=np.dot(self.FisherU, y)
		q[-self.numTime:]=newpars

	
		return q, 0



	'''
	def drawFromShapeletPrior(parameters, iter, beta):
	    
		# post-jump parameters
		q = parameters.copy()

		# transition probability
		qxy = 0

		# choose one coefficient at random to prior-draw on
		ind = np.unique(np.random.randint(1, MaxCoeff, 1))

		# where in your parameter list do the coefficients start?
		ct = 2

		for ii in ind:
		    
		    q[ct+ii] = np.random.uniform(pmin[ct+ii], pmax[ct+ii])
		    qxy += 0
	    
		return q, qxy
	'''

	def ConvolveExp(self, f, tau, returngrad=False):

		w = 2.0*np.pi*f
		fanalytic = 1.0/(w**2*tau**2+1) - 1j*w*tau/(w**2*tau**2+1)

		if(returngrad==False):
			return fanalytic
		else:
			grad = (1.0 - tau**2*w**2)/(tau**2*w**2 + 1)**2 - 1j*tau*w/(tau**2*w**2 + 1)**2 

	def GetScatteringParams(self, mode='parfile', flag = None, timestep = None):

		SXParamList = [None]*self.NToAs

		if(mode == 'parfile'):
			allparams=self.psr.pars(which='set')
			SXList = [sx for sx in allparams if 'SX_' in sx]

			self.NScatterEpochs = len(SXList)

		
			for i in range(self.NScatterEpochs):
				mintime = self.psr['SXR1_'+SXList[i][-4:]].val
				maxtime = self.psr['SXR2_'+SXList[i][-4:]].val

				select_indices = np.where(np.logical_and( self.psr.stoas < maxtime, self.psr.stoas >=mintime))[0]

				for index in select_indices:
					#print index, self.psr.stoas[index], SXList[i]
					if(SXParamList[index] == None):
						SXParamList[index] = [i]
					else:
						SXParamList[index].append(i)

		if(mode == 'flag'):
			scatterflags = np.unique(self.psr.flagvals(flag))
			self.NScatterEpochs = len(scatterflags)
			for i in range(self.NScatterEpochs):
				select_indices = np.where(self.psr.flagvals(flag) ==  scatterflags[i])[0] 
				for index in select_indices:
					print index, self.psr.stoas[index], scatterflags[i]
					if(SXParamList[index] == None):
						SXParamList[index] = [i]
					else:
						SXParamList[index].append(i)

		if(mode == 'time'):
			startMJD = np.min(self.psr.stoas)
			endMJD = np.max(self.psr.stoas)
			self.NScatterEpochs = (endMJD-startMJD)/time
			for i in range(self.NScatterEpochs):
				select_indices = np.where(np.logical_and( self.psr.stoas < startMJD+(i+1)*time, self.psr.stoas >= startMJD+i*time))[0]
				for index in select_indices:
					print index, self.psr.stoas[index]
					if(SXParamList[index] == None):
						SXParamList[index] = [i]
					else:
						SXParamList[index].append(i)

		
		return SXParamList


#def PrintEpochParams(time):
		

	def PrintEpochParams(self, time, string ='DMX'):

		time=30
		stoas = self.psr.stoas
		mintime = stoas.min()
		maxtime = stoas.max()

		NEpochs = (maxtime-mintime)/time
		Epochs=mintime - time*0.01 + np.arange(NEpochs)*time #np.linspace(mintime-time*0.01, maxtime+time*0.01, int(NEpochs+3))
		EpochList = []
		for i in range(len(Epochs)-1):
			select_indices = np.where(np.logical_and( stoas < Epochs[i+1], stoas >= Epochs[i]))[0]
			if(len(select_indices) > 0):
				EpochList.append(i)

		EpochList = np.unique(np.array(EpochList))
		for i in range(len(EpochList)):
			if(i < 9):
				print string+"_000"+str(i+1)+" -2.90883832 0"
				print string+"R1_000"+str(i+1)+" "+str(Epochs[EpochList[i]])
				print string+"R2_000"+str(i+1)+" "+str(Epochs[EpochList[i]+1])
				print string+"ER_000"+str(i+1)+" 0.20435656\n"

			if(i < 99 and i >= 9):
				print string+"_00"+str(i+1)+" -2.90883832 0"
				print string+"R1_00"+str(i+1)+" "+str(Epochs[EpochList[i]])
				print string+"R2_00"+str(i+1)+" "+str(Epochs[EpochList[i]+1])
				print string+"ER_00"+str(i+1)+" 0.20435656\n"

			if(i < 999 and i >= 99):
				print string+"_0"+str(i+1)+" -2.90883832 0"
				print string+"R1_0"+str(i+1)+" "+str(Epochs[EpochList[i]])
				print string+"R2_0"+str(i+1)+" "+str(Epochs[EpochList[i]+1])
				print string+"ER_0"+str(i+1)+" 0.20435656\n"

			if(i < 9999 and i >= 999):
				print string+"_"+str(i+1)+" -2.90883832 0"
				print string+"R1_"+str(i+1)+" "+str(Epochs[EpochList[i]])
				print string+"R2_"+str(i+1)+" "+str(Epochs[EpochList[i]+1])
				print string+"ER_"+str(i+1)+" 0.20435656\n"
