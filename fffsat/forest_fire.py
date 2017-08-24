#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2017, Panu Lahtinen / FMI
#
# Author(s):
#
#   Panu Lahtinen <panu.lahtinen@fmi.fi>

import logging

import numpy as np

from fffsat import utils


class ForestFire(object):

    """Class for creating forest fire hot spots based on algorithm by
    Planck et. al."""

    logger = logging.getLogger("ForestFire")

    def __init__(self, config):
        # Configuration dictionary for ForestFire class
        self.config = config
        # Unprojected satpy scene with all the required channels, angles and
        # coordinates
        self.data = None
        # Common mask for all the datasets in self.data
        # All invalid pixels are set as True.  After processing the locations
        # marked as False are the valid forest fires.
        self.mask = None
        # Cloud mask
        self.cloud_mask = None
        # Result of fire mapping
        self.fires = {}

    def run(self, msg=None, sat_fname=None, cma_fname=None):
        """Run everything"""
        if msg is not None:
            sat_fname, cma_fname = utils.get_filenames_from_msg(msg)
        if sat_fname is None:
            self.logger.critical("No satellite data in message")
            return False
        logging.info("Reading satellite data")
        self.data = utils.read_sat_data(sat_fname,
                                        self.config["channels_to_load"])
        if cma_fname is not None:
            logging.info("Reading PPS cloud mask")
            self.cloud_mask = utils.read_cma(cma_fname)

        # Initial mask
        self.mask = self.data[self.config["nir_chan_name"]].mask.copy()
        # Apply all masks
        self.mask_data()
        # Find hotspots
        logging.info("Finding forest fire candidates")
        self.find_hotspots()

    def save(self):
        """Save forest fires"""
        print self.fires

    def clean(self):
        """Cleanup after processing."""
        self.data = None
        self.mask = None
        self.cloud_mask = None
        self.fires = {}

    def apply_mask(self, mask):
        """Apply given mask to the product mask"""
        self.mask |= mask

    def resample_aux(self, data, lons, lats):
        """Resample auxiliary data to swath"""
        pass

    def mask_data(self):
        """Create and apply all masks"""
        logging.info("Masking data")
        for func_name in self.config["mask_functions"]:
            logging.info("Apply '%s'.", func_name)
            read_func = getattr(self, func_name)
            mask = read_func()
            self.apply_mask(mask)

    # Static masks read from a file and resampled to match the swath

    def get_land_cover_mask(self):
        """Read and resample land cover exclusion mask"""
        mask, lons, lats = \
            utils.read_land_cover(self.config["land_cover_mask"]["mask_file"])
        mask = self.resample_aux(mask, lons, lats)
        return mask

    # Masking based on data in satellite projection, either external
    # or calculated from reflectances/BTs

    def get_snow_mask(self):
        """Read and resample snow exclusion mask"""
        # Read from NWC SAF?
        mask, lons, lats = utils.read_snow_mask(self.config["mask_file"])
        mask = self.resample_aux(mask, lons, lats)
        return mask

    def get_cloud_mask(self):
        """Get exclusion mask"""
        if self.cloud_mask is not None:
            return self.cloud_mask
        else:
            self.logger.warning("NWC SAF cloud mask not available")
            return self.create_cloud_mask()

    def create_water_mask(self):
        """Create water mask"""
        # eq. 1 from Planck et. al.
        # maybe not use this?
        vis = self.data[self.config["vis_chan_name"]]
        nir = self.data[self.config["nir_chan_name"]]
        threshold = self.config["water_mask"]["threshold"]
        mean_vis_nir = (vis + nir) / 2.
        std_vis_nir = np.std(np.dstack((vis.data, nir.data)), axis=2)
        mask = ((mean_vis_nir ** 2 / std_vis_nir) < threshold) & (vis > nir)
        return mask

    def create_sun_glint_mask(self):
        """Create Sun glint mask"""
        # eq. 5 - 8 from Planck et. al.
        sat_za = np.radians(self.data[self.config["sat_za_name"]])
        sun_za = np.radians(self.data[self.config["sol_za_name"]])
        rel_aa = np.radians(self.data[self.config["rel_az_name"]])
        nir = self.data[self.config["nir_chan_name"]]

        angle_th1 = \
            np.radians(self.config["sun_glint_mask"]["angle_threshold_1"])
        angle_th2 = \
            np.radians(self.config["sun_glint_mask"]["angle_threshold_2"])
        nir_refl_th = self.config["sun_glint_mask"]["nir_refl_threshold"]

        glint = np.arccos(np.cos(sat_za) * np.cos(sun_za) -
                          np.sin(sat_za) * np.sin(sun_za) * np.cos(rel_aa))
        mask = ((glint < angle_th1) |
                ((glint < angle_th2) & (nir > nir_refl_th)))
        return mask

    def create_fcv_mask(self):
        """Calculate fraction of vegetation exclusion mask"""
        # eq. 9 and 10 from Planck et.al. 2017
        ch1 = self.data[self.config["vis_chan_name"]]
        ch2 = self.data[self.config["nir_chan_name"]]
        ndvi = (ch2 - ch1) / (ch2 + ch1)
        ndvi_min = np.min(ndvi)
        ndvi_max = np.max(ndvi)
        fcv = ((ndvi - ndvi_min) / (ndvi_max - ndvi_min)) ** 2
        mask = fcv < self.config["fcv_mask"]["threshold"]
        return mask

    def create_swath_edge_mask(self):
        """Create mask for the swath edges"""
        sza = self.data[self.config["sat_za_name"]]
        threshold = self.config["swath_edge_mask"]["threshold"]
        mask = sza > threshold
        return mask

    def create_swath_end_mask(self):
        """Create mask for the swath edges"""
        length = self.config["swath_end_mask"]["threshold"]
        mask = self.mask.copy()
        mask[0:length, :] = True
        mask[-length:, :] = True
        return mask

    def create_swath_masks(self):
        """Create both swath edge and swath end masks"""
        return (self.create_swath_edge_mask() | self.create_swath_end_mask())

    def create_cloud_mask(self):
        """Create cloud mask from satellite data."""
        # Planck et.al. 2017 eq. 2 - 4
        vis = self.data[self.config["vis_chan_name"]]
        nir = self.data[self.config["nir_chan_name"]]
        mir = self.data[self.config["mir_chan_name"]]
        ir1 = self.data[self.config["ir1_chan_name"]]
        ir2 = self.data[self.config["ir2_chan_name"]]

        w_mir = np.exp((310. - mir) / 20.)
        w_delta_ch = np.exp((mir - (ir1 + ir2) / 2. - 14.) / 14.)
        mean_vis_nir = (vis + nir) / 2.

        cloud_th = self.config["cloud_mask"]["threshold"]
        clouds = (w_mir * w_delta_ch * mean_vis_nir) > cloud_th

        return clouds

    def find_hotspots(self):
        """Find hotspots from unmasked pixels"""
        day_mask = (self.data[self.config["sol_za_name"]] <
                    self.config["sol_za_day_limit"])
        mir = self.data[self.config["mir_chan_name"]]
        ir1 = self.data[self.config["ir1_chan_name"]]
        delta_mir_ir = mir - ir1

        # Candidate mask, so that on the later probability levels there's
        # no need to recheck static mask
        candidate_mask = np.ones(self.mask.shape, dtype=np.bool)

        probs = self.config["probability_levels"]
        for lvl in probs:
            logging.info("Probability level %d", lvl)
            day_mir = probs[lvl]["day"]["temp_mir"]
            day_mir_ir = probs[lvl]["day"]["delta_mir_ir"]
            night_mir = probs[lvl]["night"]["temp_mir"]
            night_mir_ir = probs[lvl]["night"]["delta_mir_ir"]

            day_candidates = (day_mask &
                              (mir > day_mir) &
                              (delta_mir_ir > day_mir_ir))
            night_candidates = (np.invert(day_mask) &
                                (mir > night_mir) &
                                (delta_mir_ir > night_mir_ir))
            candidates = ((day_candidates | night_candidates) &
                          np.invert(self.mask) &
                          candidate_mask)

            logging.info("Initial candidates: %d", candidates.sum())
            rows, cols = np.nonzero(candidates)

            # If there's no data, exit
            if rows.size == 0:
                logging.info("No candidates found.")
                break
            # Remove invalid points using static masks
            rows, cols = self.check_static_masks(rows, cols)

            # Update candidate mask
            candidate_mask[:, :] = False
            candidate_mask[rows, cols] = True

            for i in range(len(rows)):
                quality = self.qualify_fires(rows[i], cols[i],
                                             is_day=day_mask[rows[i], cols[i]])
                self.fires[(rows[i], cols[i])] = \
                    {'quality': quality,
                     'probability': lvl,
                     'latitude': self.data[self.config['lat_name']][rows[i],
                                                                    cols[i]],
                     'longitude': self.data[self.config['lon_name']][rows[i],
                                                                     cols[i]]}

    def check_static_masks(self, rows, cols):
        """Mask data based on static masks. Return valid row and column
        indices or two empty lists if no valid pixels exist.
        """
        try:
            func_names = self.config["static_mask_functions"]
        except KeyError:
            self.logger.warning("No static masks defined")
            return rows, columns

        # Calculate footprint sizes
        sat_za = self.data[self.config["sat_za_name"]]
        ifov = self.config["ifov"]
        sat_alt = self.config["satellite_altitude"]
        along, across = \
            utils.calc_footprint_size(sat_za, ifov, sat_alt,
                                      self.config['max_swath_width'])
        lats = self.data[self.config["lat_name"]]
        lons = self.data[self.config["lon_name"]]
        self.logger.info("Checking static masks")
        idxs = utils.check_static_masks(self.logger, func_names,
                                        (lons[rows, cols], lats[rows, cols]),
                                        (along[rows, cols],
                                         across[rows, cols]))
        self.mask[rows[idxs], cols[idxs]] = True
        return rows[np.invert(idxs)], cols[np.invert(idxs)]

    def qualify_fires(self, row, col, is_day=True):
        """Check if hotspot at [row, col] is a fire or not."""
        # Get valid background pixels for MIR and IR108 channels around
        # [row, col]
        mir_bg, ir1_bg, quality = self.get_background(row, col)
        if mir_bg is None or ir1_bg is None:
            return utils.QUALITY_UNKNOWN

        mir = self.data[self.config["mir_chan_name"]][row, col]
        ir1 = self.data[self.config["ir1_chan_name"]][row, col]
        diff_mir_ir1 = mir - ir1

        # Calculate statistics
        mean_diff_bg = np.mean(mir_bg - ir1_bg)
        mad_diff_bg = utils.mean_abs_deviation(mir_bg - ir1_bg)
        mean_ir1_bg = np.mean(ir1_bg)
        mad_ir1_bg = utils.mean_abs_deviation(ir1_bg)

        if is_day:
            if ((diff_mir_ir1 > mean_diff_bg + mad_diff_bg) and
                    (ir1 > mean_ir1_bg + mad_ir1_bg - 3.)):
                return quality
            else:
                return utils.QUALITY_NOT_FIRE
        else:
            if (diff_mir_ir1 > mean_diff_bg + mad_diff_bg):
                return quality
            else:
                return utils.QUALITY_NOT_FIRE

    def get_background(self, row, col):
        """Get background data around pixel location [row, col] for MIR and
        IR108 channels.  Also return quality based on the distance from
        [row, col] to closest masked pixel (cloud, water, urban area, etc.)
        """
        bg_mir = self.config["bg_mir_temp_limit"]
        bg_delta = self.config["bg_delta_mir_ir"]
        bg_num = self.config["bg_num_valid"]
        bg_fraction = self.config["bg_fraction_valid"]

        # Ensure that 3x3 area is included for quality determination
        sides = self.config["bg_side_lengths"]
        if 3 not in sides:
            sides.insert(0, 3)

        # References to full resolution datasets needed
        full_mir = self.data[self.config["mir_chan_name"]]
        full_ir1 = self.data[self.config["ir1_chan_name"]]
        full_mask = self.mask

        mask_out = None
        mir_out = None
        ir1_out = None
        quality = utils.QUALITY_UNKNOWN

        # Sample different background areas until enough valid data are found
        for side in sides:
            # Stop looping if everything is ready
            if mask_out is not None and quality > utils.QUALITY_UNKNOWN:
                break

            # Get indices for the surrounding side x side area
            if side > 3:
                y_idxs, x_idxs = \
                    utils.get_idxs_around_location(row, col, side,
                                                   remove_neighbours=True)
            # For quality determination don't remove the surrounding pixels
            else:
                y_idxs, x_idxs = \
                    utils.get_idxs_around_location(row, col, side,
                                                   remove_neighbours=False)

            # Reference data for the area
            mir = full_mir[y_idxs, x_idxs]
            ir1 = full_ir1[y_idxs, x_idxs]
            mask = full_mask[y_idxs, x_idxs].copy()

            # Additional masking of potential background fire pixels
            potential_fires = (mir > bg_mir) & ((mir - ir1) > bg_delta)
            mask[potential_fires] = True

            # Check if there are masked pixels inside this box
            if quality == utils.QUALITY_UNKNOWN:
                if np.any(mask) or side > 5:
                    quality = \
                        utils.BOX_SIZE_TO_QUALITY.get(side,
                                                      utils.QUALITY_HIGH)

            # Find background only for boxes larger than 3x3 pixels
            if side > 3 and mask_out is None:
                if ((mask.size - mask.sum() > bg_num) and
                        (1. - mask.sum() / mask.size >= bg_fraction)):
                    # Sufficient background data found
                    mask_out = mask.copy()
                    mir_out = mir.copy()
                    ir1_out = ir1.copy()

        # Remove masked pixels
        if mask_out is not None:
            mask_out = np.invert(mask_out)
            mir_out = mir_out[mask_out].copy()
            ir1_out = ir1_out[mask_out].copy()

            return mir_out, ir1_out, quality
        else:
            return None, None, quality
