import numpy as np
import psrchive
from libstempo.libstempo import *
import libstempo as T
import matplotlib.pyplot as plt
import PTMCMCSampler
from PTMCMCSampler import PTMCMCSampler as ptmcmc
from scipy.optimize import minimize
from Class import *




lfunc = Likelihood()

lfunc.loadPulsar("Sim.par", "OneEpoch.Noise.tim")


'''Get initial Fit to the Profile'''

lfunc.TScrunch(doplot = True, channels = 1)


lfunc.getInitialParams(MaxCoeff = 2, x0=[-0.21, -1.6, np.log10(1.5)], cov_diag=[0.1, 0.1, 0.1], resume=False, outDir = './InitChains/', sampler='pal')



'''Make interpolation Matrix'''

lfunc.PreComputeShapelets(interpTime = 1, MeanBeta = lfunc.MeanBeta)

lfunc.getInitialPhase(doplot = True)
lfunc.ScatterInfo = lfunc.GetScatteringParams()




parameters = []
parameters.append('Phase')
for i in range(lfunc.MaxCoeff-1):
	for j in range(lfunc.EvoNPoly+1):
		parameters.append('S'+str(i)+'E'+str(j))
for i in range(lfunc.numTime):
	parameters.append(lfunc.psr.pars()[i])
for i in range(lfunc.NScatterEpochs):
	parameters.append("Scatter_"+str(i))


print parameters
n_params = len(parameters)
print n_params
lfunc.n_params = n_params
    
pmin = np.array(np.ones(n_params))*-100
pmax = np.array(np.ones(n_params))*100

pmin[-1] = -5


lfunc.pmin = pmin
lfunc.pmax = pmax

x0 = np.array(np.zeros(n_params))

pcount = 0
x0[pcount] = lfunc.MeanPhase
pcount += 1

for i in range(lfunc.MaxCoeff-1):
	for j in range(lfunc.EvoNPoly+1):
		x0[pcount] = lfunc.MLShapeCoeff[1+i][j]
		pcount += 1


for i in range(lfunc.numTime):
	x0[pcount+i] = 0
pcount += lfunc.numTime
for i in range(lfunc.NScatterEpochs):
	x0[pcount+i] = -2
pcount += lfunc.NScatterEpochs


lfunc.calculateHessian(x0)
covM=np.linalg.inv(lfunc.hess)
lfunc.PhasePrior = 1000*np.sqrt(covM[0,0])*lfunc.ReferencePeriod
lfunc.MeanPhase = lfunc.MeanPhase*lfunc.ReferencePeriod


'''
lfunc.calculateShapePhaseCov(x0)
ShapePhaseCov = np.linalg.inv(lfunc.ShapePhaseCov)

import scipy as sp
SPChol = sp.linalg.cholesky(ShapePhaseCov)
plist = [0,1,3,5,7,9,11]
'''

#groups=[[0,1,2,3,4,5,6,7,8,9,10,11], [0,1,2,3,4,5,6,7]]
lfunc.doplot=False
burnin=1000
sampler = ptmcmc.PTSampler(ndim=n_params,logl=lfunc.FFTMarginLogLike,logp=lfunc.my_prior,
                            cov=covM, outDir='./ScatterChain/',resume=False)
sampler.addProposalToCycle(lfunc.TimeJump, 20)
sampler.sample(p0=x0,Niter=30000,isave=10,burn=burnin,thin=1,neff=1000)
'''
chains=np.loadtxt('./FFTChains2/chain_1.txt').T
ML=chains.T[np.argmax(chains[-3][burnin:])][:n_params]
ML[0]=3.36203222e-03
x0=ML
doplot=True
MarginLogLike(x0)
doplot=False

np.savetxt("ML.dat", ML)

chains=np.loadtxt('./FFTChains2/chain_1.txt').T
ML=chains.T[burnin:][np.argmax(chains[-3][burnin:])][:n_params]
STD=np.zeros(n_params)
for i in range(n_params):
	STD[i]  =  np.std(chains[i][burnin:])
	print "param:", i, parameters[i], np.mean(chains[i][burnin:]), np.std(chains[i][burnin:])
np.savetxt("Cov.dat", STD)
cov_diag = STD
x0=ML

'''
