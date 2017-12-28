;+
; NAME:
;   LEGACYHALOS_ISEDFIT
;
; PURPOSE:
;   Use iSEDfit to compute stellar masses for the various legacyhalos samples.
;
; INPUTS:
;   At least one of /LSPHOT_DR5, /LSPHOT_CUSTOM, /SDSSPHOT_DR14, or
;   /SDSSPHOT_UPENN must be set.
;
; OPTIONAL INPUTS:
;   thissfhgrid
;
; KEYWORD PARAMETERS:
;   lsphot_dr5
;   lsphot_custom
;   sdssphot_dr14
;   sdssphot_upenn
;   write_paramfile
;   build_grids
;   model_photometry
;   isedfit
;   kcorrect
;   qaplot_sed
;   clobber
;
; OUTPUTS:
;
; COMMENTS:
;   See https://github.com/moustakas/legacyhalos for more info about the
;   fitting. 
;
; MODIFICATION HISTORY:
;   J. Moustakas, 2017 Dec 27, Siena
;
; Copyright (C) 2017, John Moustakas
; 
; This program is free software; you can redistribute it and/or modify 
; it under the terms of the GNU General Public License as published by 
; the Free Software Foundation; either version 2 of the License, or
; (at your option) any later version. 
; 
; This program is distributed in the hope that it will be useful, but 
; WITHOUT ANY WARRANTY; without even the implied warranty of
; MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
; General Public License for more details. 
;-

function lsphot_custom_version
; v1.0 - original effort    
    ver = 'v1.0'
return, ver
end    

pro legacyhalos_isedfit, lsphot_dr5=lsphot_dr5, lsphot_custom=lsphot_custom, $
  sdssphot_dr14=sdssphot_dr14, sdssphot_upenn=sdssphot_upenn, write_paramfile=write_paramfile, $
  build_grids=build_grids, model_photometry=model_photometry, isedfit=isedfit, $
  kcorrect=kcorrect, qaplot_sed=qaplot_sed, thissfhgrid=thissfhgrid, $
  clobber=clobber

;   echo "legacyhalos_isedfit, /lsphot_dr5, /write_param, /build_grids, /model_phot, /isedfit, /kcorrect, /cl" | /usr/bin/nohup idl > lsphot-dr5.log 2>&1 &
;   echo "legacyhalos_isedfit, /sdssphot_dr14, /write_param, /build_grids, /model_phot, /isedfit, /kcorrect, /cl" | /usr/bin/nohup idl > sdssphot-dr14.log 2>&1 &

    legacyhalos_dir = getenv('LEGACYHALOS_DIR')

    if keyword_set(lsphot_dr5) eq 0 and keyword_set(lsphot_custom) eq 0 and $
      keyword_set(sdssphot_dr14) eq 0 and keyword_set(sdssphot_upenn) eq 0 then begin
       splog, 'Choose one of /LSPHOT_DR5, /LSPHOT_CUSTOM, /SDSSPHOT_DR14, or /SDSSPHOT_UPENN'
       return       
    endif
    
; directories and prefixes for each dataset
    if keyword_set(lsphot_dr5) then begin
       prefix = 'lsphot'
       outprefix = 'lsphot_dr5'
    endif
    if keyword_set(lsphot_custom) then begin
       version = lsphot_custom_version()
       prefix = 'lsphot'
       outprefix = 'lsphot_'+version
    endif
    if keyword_set(sdssphot_dr14) then begin
       prefix = 'sdssphot'
       outprefix = 'sdssphot_dr14'
    endif
    if keyword_set(sdssphot_upenn) then begin
       prefix = 'sdssphot'
       outprefix = 'sdssphot_upenn'
    endif
    
    isedfit_dir = getenv('IM_ARCHIVE_DIR')+'/projects/legacyhalos/isedfit_'+prefix+'/'
    montegrids_dir = getenv('IM_ARCHIVE_DIR')+'/projects/legacyhalos/montegrids_'+prefix+'/'
    isedfit_paramfile = isedfit_dir+prefix+'_paramfile.par'

    spawn, ['mkdir -p '+isedfit_dir], /sh
    spawn, ['mkdir -p '+montegrids_dir], /sh

; define the filters and the redshift ranges
    if keyword_set(lsphot_dr5) or keyword_set(lsphot_custom) then begin
       filterlist = [legacysurvey_filterlist(), wise_filterlist(/short)]
       zminmax = [0.05,0.6]
       nzz = 61
    endif
    if keyword_set(sdssphot_dr14) then begin
       filterlist = [sdss_filterlist(), wise_filterlist(/short)]
       zminmax = [0.05,0.6]
       nzz = 61
    endif
    if keyword_set(sdssphot_upenn) then begin
       filterlist = [sdss_filterlist(), wise_filterlist(/short)] ; most of these will be zeros
       zminmax = [0.05,0.4]
       nzz = 41
    endif
    
; DR5 LegacySurvey (grz) + unWISE W1 & W2    
    if keyword_set(lsphot_dr5) then begin
       rm = mrdfits(legacyhalos_dir+'/legacyhalos-parent.fits', 'REDMAPPER')
       cat = mrdfits(legacyhalos_dir+'/legacyhalos-parent.fits', 'LSPHOT')
       ngal = n_elements(cat)

       ra = rm.ra
       dec = rm.dec
       zobj = rm.z
       
       factor = 1D-9 / transpose([ [cat.mw_transmission_g], [cat.mw_transmission_r], $
         [cat.mw_transmission_z] ])
       dmaggies = float(transpose([ [cat.flux_g], [cat.flux_r], [cat.flux_z] ]) * factor)
       divarmaggies = float(transpose([ [cat.flux_ivar_g], [cat.flux_ivar_r], $
         [cat.flux_ivar_z] ]) / factor^2)
       
       factor = 1D-9 / transpose([ [cat.mw_transmission_w1], [cat.mw_transmission_w2] ])
       wmaggies = float(transpose([ [cat.flux_w1], [cat.flux_w2] ]) * factor)
       wivarmaggies = float(transpose([ [cat.flux_ivar_w1], [cat.flux_ivar_w2] ]) / factor^2)

       maggies = [dmaggies, wmaggies]
       ivarmaggies = [divarmaggies, wivarmaggies]

; mask out wonky unWISE photometry
       snr = maggies*sqrt(ivarmaggies)
       ww = where(abs(snr[3,*]) gt 1e3) & ivarmaggies[3,ww] = 0
       ww = where(abs(snr[4,*]) gt 1e3) & ivarmaggies[4,ww] = 0
    endif
    
; custom LegacySurvey (grz) + unWISE W1 & W2    
    if keyword_set(lsphot_custom) then begin
       splog, 'Not yet available!'
       stop
    endif

; SDSS ugriz + forced WISE photometry from Lang & Schlegel    
    if keyword_set(sdssphot_dr14) then begin
       rm = mrdfits(legacyhalos_dir+'/legacyhalos-parent.fits', 'REDMAPPER')
       cat = mrdfits(legacyhalos_dir+'/legacyhalos-parent.fits', 'SDSSPHOT')
       ngal = n_elements(cat)

       ra = rm.ra
       dec = rm.dec
       zobj = rm.z
       
       ratio = cat.cmodelmaggies[2,*]/cat.modelmaggies[2,*]
       factor = 1D-9 * rebin(ratio, 5, ngal) * 10D^(0.4*cat.extinction)
       smaggies = cat.modelmaggies * factor
       sivarmaggies = cat.modelmaggies_ivar / factor^2

       vega2ab = rebin([2.699,3.339],2,ngal) ; Vega-->AB from http://legacysurvey.org/dr5/description/#photometry
       glactc, rm.ra, rm.dec, 2000.0, gl, gb, 1, /deg
       ebv = rebin(reform(dust_getval(gl,gb,/interp,/noloop),1,ngal),2,ngal)
       coeff = rebin(reform([0.184,0.113],2,1),2,ngal) ; Galactic extinction coefficients from http://legacysurvey.org/dr5/catalogs
       
       factor = 1D-9 * 10^(0.4*coeff*ebv)*10^(-0.4*vega2ab) ; * 1D-9; * 1D-9
       wmaggies = float(cat.wise_nanomaggies * factor)
       wivarmaggies = float(cat.wise_nanomaggies_ivar / factor^2)
       
       maggies = [smaggies, wmaggies]
       ivarmaggies = [sivarmaggies, wivarmaggies]
       
;      print, -2.5*alog10(maggies[*,0:10])
    endif

; UPenn-PhotDec gri SDSS photometry
    if keyword_set(sdssphot_upenn) then begin
       rm = mrdfits(legacyhalos_dir+'/legacyhalos-upenn-parent.fits', 'REDMAPPER')
       cat = mrdfits(legacyhalos_dir+'/legacyhalos-upenn-parent.fits', 'UPENN')
       ngal = n_elements(cat)

       ra = rm.ra
       dec = rm.dec
       zobj = rm.z
       
       splog, 'Write some photometry code here!'
       stop
    endif

; --------------------------------------------------
; write the parameter file
    if keyword_set(write_paramfile) then begin
       spsmodels = 'fsps_v2.4_miles' ; v1.0
       imf = 'chab'
       redcurve = 'charlot'
       Zmetal = [0.004,0.03]
       age = [0.1,13.0]
       tau = [0.0,6]
       nmodel = 25000L

       write_isedfit_paramfile, params=params, isedfit_dir=isedfit_dir, $
         prefix=prefix, filterlist=filterlist, spsmodels=spsmodels, $
         imf=imf, redcurve=redcurve, igm=0, zminmax=zminmax, nzz=nzz, $
         nmodel=nmodel, age=age, tau=tau, Zmetal=Zmetal, $
         /delayed, nebular=0, clobber=clobber, sfhgrid=lsphot_sfhgrid
    endif

;   splog, 'HACK!!'
;   index = lindgen(100)
;   jj = mrdfits('lsphot_dr5_fsps_v2.4_miles_chab_charlot_sfhgrid01.fits.gz',1)
;   index = where(jj.mstar lt 0)
;   outprefix = 'test'

; --------------------------------------------------
; build the Monte Carlo grids    
    if keyword_set(build_grids) then begin
       isedfit_montegrids, isedfit_paramfile, isedfit_dir=isedfit_dir, $
         montegrids_dir=montegrids_dir, thissfhgrid=thissfhgrid, clobber=clobber
    endif

; --------------------------------------------------
; calculate the model photometry 
    if keyword_set(model_photometry) then begin
       isedfit_models, isedfit_paramfile, isedfit_dir=isedfit_dir, $
         montegrids_dir=montegrids_dir, thissfhgrid=thissfhgrid, $
         clobber=clobber
    endif

; --------------------------------------------------
; fit!
    if keyword_set(isedfit) then begin
       isedfit, isedfit_paramfile, maggies, ivarmaggies, zobj, ra=ra, $
         dec=dec, isedfit_dir=isedfit_dir, thissfhgrid=thissfhgrid, $
         clobber=clobber, index=index, outprefix=outprefix
    endif 

; --------------------------------------------------
; compute K-corrections
    if keyword_set(kcorrect) then begin
       isedfit_kcorrect, isedfit_paramfile, isedfit_dir=isedfit_dir, $
         montegrids_dir=montegrids_dir, thissfhgrid=thissfhgrid, $
         absmag_filterlist=legacysurvey_filterlist(), band_shift=0.0, $
         clobber=clobber, index=index, outprefix=outprefix
    endif 

; --------------------------------------------------
; generate spectral energy distribution (SED) QAplots
    if keyword_set(qaplot_sed) then begin
       these = lindgen(50)
       isedfit_qaplot_sed, isedfit_paramfile, isedfit_dir=isedfit_dir, $
         montegrids_dir=montegrids_dir, outprefix=outprefix, thissfhgrid=thissfhgrid, $
         clobber=clobber, index=these, /xlog
    endif

return
end
