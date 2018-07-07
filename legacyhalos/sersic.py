"""
legacyhalos.sersic
==================

Code to do Sersic on the surface brightness profiles.

"""
from __future__ import absolute_import, division, print_function

import os, pdb
import time, warnings

import numpy as np
import numpy.ma as ma
import matplotlib.pyplot as plt

from astropy.modeling import Fittable2DModel

import legacyhalos.io

import seaborn as sns
sns.set(style='ticks', font_scale=1.4, palette='Set2')

class SersicSingleWaveModel(Fittable2DModel):
    """
    Define a surface brightness profile model which is three single Sersic
    models connected by a Sersic index and half-light radius which varies
    as a power-law function of wavelength.
    
    See http://docs.astropy.org/en/stable/modeling/new.html#a-step-by-step-definition-of-a-1-d-gaussian-model
    for useful info.

    """
    from astropy.modeling import Parameter
    
    nref = Parameter(default=4, bounds=(0.1, 8))
    r50ref = Parameter(default=10, bounds=(1e-3, 30)) # [arcsec]
    alpha = Parameter(default=0.0, bounds=(-1, 1))
    beta = Parameter(default=0.0, bounds=(-1, 1))
    mu50_g = Parameter(default=1.0)#, bounds=(1e-3, 1e3)) # [nanomaggies at r50] [mag=15-30]
    mu50_r = Parameter(default=1.0)#, bounds=(1e-3, 1e3))
    mu50_z = Parameter(default=1.0)#, bounds=(1e-3, 1e3))

    linear = False
    
    def __init__(self, nref=nref.default, r50ref=r50ref.default, 
                 alpha=alpha.default, beta=beta.default, 
                 mu50_g=mu50_g.default, mu50_r=mu50_r.default, mu50_z=mu50_z.default, 
                 psfsigma_g=0.0, psfsigma_r=0.0, psfsigma_z=0.0, 
                 lambda_ref=6470, lambda_g=4890, lambda_r=6470, lambda_z=9196, 
                 **kwargs):

        self.band = ('g', 'r', 'z')
        
        #from speclite import filters
        #filt = filters.load_filters('decam2014-g', 'decam2014-r', 'decam2014-z')
        #print(filt.effective_wavelengths.value)
        
        self.lambda_g = lambda_g
        self.lambda_r = lambda_r
        self.lambda_z = lambda_z
        self.lambda_ref = lambda_ref
        
        self.psfsigma_g = psfsigma_g
        self.psfsigma_r = psfsigma_r
        self.psfsigma_z = psfsigma_z
        
        super(SersicSingleWaveModel, self).__init__(nref=nref, r50ref=r50ref, alpha=alpha, 
                                                    beta=beta, mu50_g=mu50_g, mu50_r=mu50_r, 
                                                    mu50_z=mu50_z, **kwargs)
        
    def get_sersicn(self, nref, lam, alpha):
        return nref * (lam / self.lambda_ref)**alpha
    
    def get_r50(self, r50ref, lam, beta):
        return r50ref * (lam / self.lambda_ref)**beta
    
    def evaluate(self, r, w, nref, r50ref, alpha, beta, mu50_g, mu50_r, mu50_z):
        """Evaluate the wavelength-dependent Sersic model.
        
        Args:
          r : radius [kpc]
          w : wavelength [Angstrom]
          nref : Sersic index at the reference wavelength lambda_ref
          r50ref : half-light radius at lambda_ref
          alpha : power-law slope for the Sersic index
          beta : power-law slope for the half-light radius
          mu50_g : g-band surface brignthess at r=r50_g
          mu50_r : r-band surface brignthess at r=r50_r
          mu50_z : z-band surface brignthess at r=r50_z
        
        """
        from scipy.special import gammaincinv
        from astropy.convolution import Gaussian1DKernel, convolve
        
        mu = np.zeros_like(r)
        
        # Build the surface brightness profile at each wavelength.
        for lam, psfsig, mu50 in zip( (self.lambda_g, self.lambda_r, self.lambda_z), 
                                      (self.psfsigma_g, self.psfsigma_r, self.psfsigma_z), 
                                      (mu50_g, mu50_r, mu50_z) ):
            
            n = self.get_sersicn(nref, lam, alpha)
            r50 = self.get_r50(r50ref, lam, beta)
            
            indx = w == lam
            if np.sum(indx) > 0:
                mu_int = mu50 * np.exp(-gammaincinv(2 * n, 0.5) * ((r[indx] / r50) ** (1 / n) - 1))
            
                # smooth with the PSF
                if psfsig > 0:
                    g = Gaussian1DKernel(stddev=psfsig)#, mode='linear_interp')
                    mu_smooth = convolve(mu_int, g, normalize_kernel=True, boundary='extend')
                    fix = (r[indx] > 5 * psfsig)
                    mu_smooth[fix] = mu_int[fix] # replace with original values
                    mu[indx] = mu_smooth
                else:
                    mu[indx] = mu_int
        
        return mu
    
class SersicSingleWaveFit(object):
    """Fit surface brightness profiles with the SersicSingleWaveModel model."""
    
    def __init__(self, sbprofile, fix_alpha=False, fix_beta=False, seed=None):
        """sbprofile is the output of legacyhalos.util.ellipse_sbprofile
        
        """
        from astropy.modeling import fitting

        self.rand = np.random.RandomState(seed)
        
        # initialize the fitter
        self.fitter = fitting.LevMarLSQFitter()
        
        # initialize the fit (need to "ball" this step and include the PSF width!)
        self.fixed = {'alpha': fix_alpha, 'beta': fix_beta}
        self.initfit = SersicSingleWaveModel(fixed=self.fixed,
                                             psfsigma_g=sbprofile['psfsigma_g'],
                                             psfsigma_r=sbprofile['psfsigma_r'],
                                             psfsigma_z=sbprofile['psfsigma_z'])
        self.nparams = len(self.initfit.parameters)

        # parse the input sbprofile into the format that SersicSingleWaveModel() expects
        sb, sberr, wave, radius = [], [], [], []
        for band, lam in zip( self.initfit.band, (self.initfit.lambda_g, 
                                                  self.initfit.lambda_r, 
                                                  self.initfit.lambda_z) ):
            # any quality cuts on stop_code here?!?
            wave.append(np.repeat(lam, len(sbprofile['sma'])))
            rad = sbprofile['sma'] # must be in arcsec!
            
            flux, ferr = self._mu2flux(mu=sbprofile['mu_{}'.format(band)],
                                       muerr=sbprofile['mu_{}_err'.format(band)])
            
            radius.append(rad)
            sb.append(flux)
            sberr.append(ferr)

        self.sb = np.hstack(sb)
        self.sberr = np.hstack(sberr)
        self.wave = np.hstack(wave)
        self.radius = np.hstack(radius)
        self.redshift = sbprofile['redshift']

    def _mu2flux(self, mu, muerr=None):
        """Convert surface brightness mu to linear flux in nanomaggies."""
        flux = 10**( -0.4 * (mu - 22.5) )
        if muerr is not None:
            ferr = 0.4 * np.log(10) * flux * muerr
            return flux, ferr
        else:
            return flux
    
    def chi2(self, bestfit):
        dof = len(self.sb) - len(bestfit.parameters)
        chi2 = np.sum( (self.sb - bestfit(self.radius, self.wave, self.sb))**2 / self.sberr**2 ) / dof
        return chi2
    
    def integrate(self, bestfit, nrad=50):
        """Integrated the data and the model to get the final photometry.
        
        flux_obs_[grz] : observed integrated flux
        flux_int_[grz] : integrated (extrapolated) flux
        deltamag_in_[grz] : flux extrapolated inward
        deltamag_out_[grz] : flux extrapolated outward
        deltamag_[grz] : magnitude correction between flux_obs_[grz] and flux_int_[grz] or
          deltamag_in_[grz] + deltamag_out_[grz]
        
        """
        from scipy import integrate
        from astropy.table import Table, Column

        phot = Table()
        [phot.add_column(Column(name='flux_obs_{}'.format(bb), dtype='f4', length=1)) for bb in self.initfit.band]
        [phot.add_column(Column(name='flux_{}'.format(bb), dtype='f4', length=1)) for bb in self.initfit.band]
        [phot.add_column(Column(name='dm_in_{}'.format(bb), dtype='f4', length=1)) for bb in self.initfit.band]
        [phot.add_column(Column(name='dm_out_{}'.format(bb), dtype='f4', length=1)) for bb in self.initfit.band]
        [phot.add_column(Column(name='dm_{}'.format(bb), dtype='f4', length=1)) for bb in self.initfit.band]

        for band, lam in zip( self.initfit.band, (self.initfit.lambda_g, 
                                                  self.initfit.lambda_r, 
                                                  self.initfit.lambda_z) ):
            wave = np.repeat(lam, nrad)
            indx = self.wave == lam
            
            rad = self.radius[indx]
            sb = self.sb[indx]
            phot['flux_obs_{}'.format(band)] = 2 * np.pi * integrate.simps(x=rad, y=rad*sb)
            
            # now integrate inward and outward by evaluating the model
            rad_in = np.linspace(0, rad.min(), nrad)
            sb_in = bestfit(rad_in, wave)
            dm_in = 2 * np.pi * integrate.simps(x=rad_in, y=rad_in*sb_in)
            
            rad_out = np.logspace(np.log10(rad.max()), 3, nrad)
            sb_out = bestfit(rad_out, wave)
            dm_out = 2 * np.pi * integrate.simps(x=rad_out, y=rad_out*sb_out)
            
            dm = dm_in + dm_out
            phot['flux_{}'.format(band)] = phot['flux_obs_{}'.format(band)] + dm
            
            phot['dm_in_{}'.format(band)] = 22.5 - 2.5 * np.log10(dm_in)
            phot['dm_out_{}'.format(band)] = 22.5 - 2.5 * np.log10(dm_out)
            phot['dm_{}'.format(band)] = 22.5 - 2.5 * np.log10(dm)
            
        return phot

    def fit(self, nball=10, chi2fail=1e6, verbose=False):
        """Perform the chi2 minimization.
        
        """
        import warnings
        if verbose:
            warnvalue = 'always'
        else:
            warnvalue = 'ignore'

        # initialize the output dictionary
        result = {
            'success': False,
            'redshift': self.redshift,
            'radius': self.radius,
            'wave': self.wave,
            'sb': self.sb,
            'sberr': self.sberr,
            'band': self.initfit.band,
            'lambda_g': self.initfit.lambda_g,
            'lambda_r': self.initfit.lambda_r,
            'lambda_z': self.initfit.lambda_z}

        # perturb the parameter values
        params = np.repeat(self.initfit.parameters, nball).reshape(self.nparams, nball)
        for ii, pp in enumerate(self.initfit.param_names):
            pinfo = getattr(self.initfit, pp)
            if pinfo.bounds[0] is not None:
                params[ii, :] = self.rand.uniform(pinfo.bounds[0], pinfo.bounds[1], nball)
            else:
                params[ii, :] += self.rand.normal(scale=0.1*params[ii, :], size=nball)
        
        # perform the fit several times
        with warnings.catch_warnings():
            warnings.simplefilter(warnvalue)
            
            chi2 = np.zeros(nball) + chi2fail
            for jj in range(nball):
                self.initfit.parameters = params[:, jj]
                ballfit = self.fitter(self.initfit, self.radius, self.wave, self.sb,
                                      weights=1/self.sberr, maxiter=200)
                if self.fitter.fit_info['param_cov'] is not None: # failed
                    chi2[jj] = self.chi2(ballfit)
                    params[:, jj] = ballfit.parameters # update

        # did at least one fit succeed?
        good = chi2 < chi2fail
        if np.sum(good) == 0:
            print('Single-Sersic fitting failed.')
            return result

        # otherwise, re-evaluate the model at the chi2 minimum
        result['success'] = True
        mindx = np.argmin(chi2)

        self.initfit.parameters = params[:, mindx]
        bestfit = self.fitter(self.initfit, self.radius, self.wave, 
                              self.sb, weights=1/self.sberr)
        chi2 = chi2[mindx]
        print('Single-Sersic fitting succeeded with a chi^2 minimum of {:.2f}'.format(chi2))

        # Integrate the data and model over various apertures.
        phot = self.integrate(bestfit)
        
        # Pack the results in a dictionary and return.
        # https://gist.github.com/eteq/1f3f0cec9e4f27536d52cd59054c55f2
        cov = self.fitter.fit_info['param_cov'] 

        result.update({
            'param_names': bestfit.param_names,
            'values': bestfit.parameters,
            'uncertainties': np.diag(cov)**0.5,
            'cov': cov,
            'chi2': chi2,
            'dof': len(self.sb) - len(bestfit.parameters),
            'bestfit': bestfit,
            'fit_message': self.fitter.fit_info['message'],
            'phot': phot,
        })
        
        return result

def sersic_single(objid, objdir, sbprofile, seed=None, nowrite=False, verbose=False):
    """Wrapper to fit a single Sersic model to an input surface brightness profile. 

    """
    
    sersic = SersicSingleWaveFit(sbprofile, fix_alpha=False, fix_beta=False, seed=seed)
    sersic = sersic.fit()

    if not nowrite:
        legacyhalos.io.write_sersic(objid, objdir, sersic, verbose=verbose)

    return sersic

def legacyhalos_sersic(sample, objid=None, objdir=None, verbose=False, debug=False):
    """Top-level wrapper script to model the measured surface-brightness profiles
    with various Sersic models.

    """ 
    from legacyhalos.ellipse import ellipse_sbprofile

    if objid is None and objdir is None:
        objid, objdir = get_objid(sample)

    # Read the ellipse-fitting results and 
    ellipsefit = legacyhalos.io.read_ellipsefit(objid, objdir)
    if bool(ellipsefit):
        if ellipsefit['success']:
            sbprofile = ellipse_sbprofile(ellipsefit, minerr=0.03)

            # Single-sersic fit
            single = sersic_single(objid, objdir, sbprofile, verbose=verbose)

            if single['success']:
                return 1
            else:
                return 0
        else:
            return 0
    else:
        return 0