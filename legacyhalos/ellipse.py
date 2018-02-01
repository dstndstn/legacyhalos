"""
legacyhalos.ellipse
===================

Code to do ellipse fitting on the residual coadds.

"""
from __future__ import absolute_import, division, print_function

import os
import time
import numpy as np
import matplotlib.pyplot as plt

import legacyhalos.io

import seaborn as sns
sns.set(context='talk', style='ticks')#, palette='Set1')
    
PIXSCALE = 0.262

def _initial_ellipse(cat, pixscale=PIXSCALE, data=None, refband='r',
                     verbose=False, use_tractor=False):
    """Initialize an Ellipse object by converting the Tractor ellipticity
    measurements to eccentricity and position angle.  See
    http://legacysurvey.org/dr5/catalogs and
    http://photutils.readthedocs.io/en/stable/isophote_faq.html#isophote-faq for
    more details.

    """
    nx, ny = data[refband].shape

    galtype = cat.type.strip().upper()
    if galtype == 'DEV':
        sma = cat.shapedev_r / pixscale # [pixels]
    else:
        sma = cat.shapeexp_r / pixscale # [pixels]

    if sma == 0:
        sma = 10
        
    if use_tractor:
        if galtype == 'DEV':
            epsilon = np.sqrt(cat.shapedev_e1**2 + cat.shapedev_e2**2)
            pa = 0.5 * np.arctan(cat.shapedev_e2 / cat.shapedev_e1)
        else:
            epsilon = np.sqrt(cat.shapeexp_e1**2 + cat.shapeexp_e2**2)
            pa = 0.5 * np.arctan(cat.shapeexp_e2 / cat.shapeexp_e1)
            
        ba = (1 - np.abs(epsilon)) / (1 + np.abs(epsilon))
        eps = 1 - ba
    else:
        from mge.find_galaxy import find_galaxy
        ff = find_galaxy(data[refband], plot=False, quiet=not verbose)
        eps, pa = ff.eps, np.radians(ff.theta)

    if verbose:
        print('Type={}, sma={:.2f}, eps={:.2f}, pa={:.2f} (initial)'.format(
            galtype, sma, eps, np.degrees(pa)))

    geometry = EllipseGeometry(x0=nx/2, y0=ny/2, sma=sma, eps=eps, pa=pa)
    ellaper = EllipticalAperture((geometry.x0, geometry.y0), geometry.sma,
                                 geometry.sma*(1 - geometry.eps), geometry.pa)
    return geometry, ellaper

def ellipsefit_multiband(objid, objdir, data, mgefit, band=('g', 'r', 'z'), refband='r',
                         integrmode='bilinear', sclip=5, nclip=3, step=0.1, verbose=False):
    """Ellipse-fit the multiband data.

    See
    https://github.com/astropy/photutils-datasets/blob/master/notebooks/isophote/isophote_example4.ipynb

    """
    from photutils.isophote import (EllipseGeometry, Ellipse, EllipseSample,
                                    Isophote, IsophoteList)

    # http://photutils.readthedocs.io/en/stable/isophote_faq.html#isophote-faq
    # Note: position angle in photutils is measured counter-clockwise from the
    # x-axis, while .pa in MGE measured counter-clockwise from the y-axis.
    if verbose:
        print('Initializing an Ellipse object in the reference {}-band image.'.format(refband))
    geometry = EllipseGeometry(x0=mgefit[refband].xmed, y0=mgefit[refband].ymed,
                               sma=0.5*mgefit[refband].majoraxis, eps=mgefit[refband].eps,
                               pa=np.radians(-mgefit[refband].theta))
    
    #print('QA for debugging.')
    #display_multiband(data, geometry=geometry, band=band, mgefit=mgefit)

    ellipsefit = dict()
    ellipsefit['{}_geometry'.format(refband)] = geometry

    # Fit in the reference band...
    if verbose:
        print('Ellipse-fitting the reference {}-band image.'.format(refband))
    t0 = time.time()

    img = data['{}_masked'.format(refband)]
    ellipse = Ellipse(img, geometry)
    ellipsefit[refband] = ellipse.fit_image(minsma=0.0, maxsma=None, integrmode=integrmode,
                                            sclip=sclip, nclip=nclip, step=step, linear=True)
    import pdb ; pdb.set_trace()

    if verbose:
        print('Time = {:.3f} sec'.format( (time.time() - t0) / 1))

    tall = time.time()
    for filt in band:
        t0 = time.time()
        if verbose:
            print('Ellipse-fitting {}-band image.'.format(filt))

        if filt == refband: # we did it already!
            continue

        # Loop on the reference band isophotes.
        isobandfit = []
        for iso in ellipsefit[refband]:

            g = iso.sample.geometry # fixed geometry

            # Use the same integration mode and clipping parameters.
            img = data['{}_masked'.format(filt)]
            sample = EllipseSample(img, g.sma, geometry=g, integrmode=integrmode,
                                   sclip=sclip, nclip=nclip)
            sample.update()

            # Create an Isophote instance with the sample.
            isobandfit.append(Isophote(sample, 0, True, 0))

        # Build the IsophoteList instance with the result.
        ellipsefit[filt] = IsophoteList(isobandfit)
        if verbose:
            print('Time = {:.3f} sec'.format( (time.time() - t0) / 1))

    if verbose:
        print('Time for all images = {:.3f} sec'.format( (time.time() - tall) / 1))

    # Write out
    legacyhalos.io.write_ellipsefit(objid, objdir, ellipsefit, verbose=verbose)

    return ellipsefit

def mgefit_multiband(objid, objdir, data, band=('g', 'r', 'z'), refband='r',
                     pixscale=0.262, debug=False, verbose=False):
    """MGE-fit the multiband data.

    See http://www-astro.physics.ox.ac.uk/~mxc/software/#mge

    """
    from mge.find_galaxy import find_galaxy
    from mge.sectors_photometry import sectors_photometry
    from mge.mge_fit_sectors import mge_fit_sectors as fit_sectors
    from mge.mge_print_contours import mge_print_contours as print_contours

    # Get the geometry of the galaxy in the reference band.
    if verbose:
        print('Finding the galaxy in the reference {}-band image.'.format(refband))

    galaxy = find_galaxy(data[refband], nblob=1, plot=debug, quiet=not verbose)
    if debug:
        plt.show()

    t0 = time.time()
    
    mgefit = dict()
    for filt in band:

        if verbose:
            print('Running MGE on the {}-band image.'.format(filt))

        mgephot = sectors_photometry(data[filt], galaxy.eps, galaxy.theta, galaxy.xpeak,
                                     galaxy.ypeak, n_sectors=11, minlevel=0, plot=debug,
                                     mask=data['{}_mask'.format(filt)])
        if debug:
            plt.show()

        _mgefit = fit_sectors(mgephot.radius, mgephot.angle, mgephot.counts, galaxy.eps,
                              ngauss=None, negative=False, sigmaPSF=0, normPSF=1,
                              scale=pixscale, quiet=not debug, outer_slope=4,
                              bulge_disk=False, plot=debug)
        _mgefit.eps = galaxy.eps
        _mgefit.majoraxis = galaxy.majoraxis # major axis length in pixels
        _mgefit.pa = galaxy.pa
        _mgefit.theta = galaxy.theta
        _mgefit.xmed = galaxy.xmed
        _mgefit.xpeak = galaxy.xpeak
        _mgefit.ymed = galaxy.ymed
        _mgefit.ypeak = galaxy.ypeak
        
        mgefit[filt] = _mgefit

        if debug:
            plt.show()

        #plt.clf()
        #plt.scatter(phot.radius, 22.5-2.5*np.log10(phot.counts), s=20)
        ##plt.scatter(phot2.radius, 22.5-2.5*np.log10(phot2.counts), s=20)
        #plt.ylim(34, 20)
        #plt.show()        

        #_ = print_contours(data[refband], galaxy.pa, galaxy.xpeak, galaxy.ypeak, pp.sol, 
        #                   binning=2, normpsf=1, magrange=6, mask=None, 
        #                   scale=pixscale, sigmapsf=0)

    legacyhalos.io.write_mgefit(objid, objdir, mgefit, band=refband, verbose=verbose)

    if verbose:
        print('Time = {:.3f} sec'.format( (time.time() - t0) / 1))

    return mgefit
    
def legacyhalos_ellipse(galaxycat, objid=None, objdir=None, ncpu=1,
                        pixscale=0.262, refband='r', band=('g', 'r', 'z'),
                        verbose=False, debug=False):
    """Top-level wrapper script to do ellipse-fitting on a single galaxy.

    photutils - do ellipse-fitting using photutils, otherwise use MGE.

    """ 
    if objid is None and objdir is None:
        objid, objdir = get_objid(galaxycat)

    # Read the data.  
    data = legacyhalos.io.read_multiband(objid, objdir, band=band)

    # Find the galaxy and perform MGE fitting
    mgefit = mgefit_multiband(objid, objdir, data, band=band, refband=refband,
                              pixscale=pixscale, verbose=verbose, debug=debug)

    # Do ellipse-fitting
    ellipsefit = ellipsefit_multiband(objid, objdir, data, mgefit, band=band,
                                      refband=refband, verbose=verbose)

    return 1 # success!
