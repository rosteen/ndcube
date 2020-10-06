# Author: Ankit Baruah and Daniel Ryan <ryand5@tcd.ie>

"""
Miscellaneous WCS utilities.
"""

import re
from copy import deepcopy
from collections import UserDict
import numbers

import numpy as np
from astropy import wcs
from astropy.wcs._wcs import InconsistentAxisTypesError

from ndcube.utils import cube as utils_cube

__all__ = ['WCS', 'reindex_wcs', 'wcs_ivoa_mapping', 'get_dependent_data_axes',
           'get_dependent_data_axes', 'axis_correlation_matrix',
           'append_sequence_axis_to_wcs']


class TwoWayDict(UserDict):
    @property
    def inv(self):
        """
        The inverse dictionary.
        """
        return {v: k for k, v in self.items()}


# Define a two way dictionary to hold translations between WCS axis
# types and International Virtual Observatory Alliance vocabulary.
# See http://www.ivoa.net/documents/REC/UCD/UCDlist-20070402.html
wcs_to_ivoa = {
    "HPLT": "custom:pos.helioprojective.lat",
    "HPLN": "custom:pos.helioprojective.lon",
    "TIME": "time",
    "WAVE": "em.wl",
    "RA--": "pos.eq.ra",
    "DEC-": "pos.eq.dec",
    "FREQ": "em.freq",
    "STOKES": "phys.polarization.stokes",
    "PIXEL": "instr.pixel",
    "XPIXEL": "custom:instr.pixel.x",
    "YPIXEL": "custom:instr.pixel.y",
    "ZPIXEL": "custom:instr.pixel.z"
}
wcs_ivoa_mapping = TwoWayDict()
for key in wcs_to_ivoa.keys():
    wcs_ivoa_mapping[key] = wcs_to_ivoa[key]


class WCS(wcs.WCS):

    def __init__(self, header=None, naxis=None, **kwargs):
        """
        Initiates a WCS object with additional functionality to add dummy axes.

        Not all WCS axes are independent.  Some, e.g. latitude and longitude,
        are dependent and one cannot be used without the other.  Therefore this
        WCS class has the ability to determine whether a dependent axis is missing
        and can augment the WCS axes with a dummy axis to enable the translations
        to work.

        Parameters
        ----------
        header: FITS header or `dict` with appropriate FITS keywords.

        naxis: `int`
            Number of axis described by the header.
        """
        self.oriented = False
        self.was_augmented = WCS._needs_augmenting(header)
        if self.was_augmented:
            header = WCS._augment(header, naxis)
            if naxis is not None:
                naxis = naxis + 1
        super().__init__(header=header, naxis=naxis, **kwargs)

    @classmethod
    def _needs_augmenting(cls, header):
        """
        Determines whether a missing dependent axis is missing from the WCS
        object.

        WCS cannot be created with only one spacial dimension. If
        WCS detects that returns that it needs to be augmented.

        Parameters
        ----------
        header: FITS header or `dict` with appropriate FITS keywords.
        """
        try:
            wcs.WCS(header=header)
        except InconsistentAxisTypesError as err:
            if re.search(r'Unmatched celestial axes', str(err)):
                return True
        return False

    @classmethod
    def _augment(cls, header, naxis):
        """
        Augments WCS with a dummy axis to take the place of a missing dependent
        axis.
        """
        newheader = deepcopy(header)
        new_wcs_axes_params = {'CRPIX': 0, 'CDELT': 1, 'CRVAL': 0,
                               'CNAME': 'redundant axis', 'CTYPE': 'HPLN-TAN',
                               'CROTA': 0, 'CUNIT': 'deg', 'NAXIS': 1}
        axis = str(max(newheader.get('NAXIS', 0), naxis) + 1)
        for param in new_wcs_axes_params:
            attr = new_wcs_axes_params[param]
            newheader[param + axis] = attr
        try:
            print(wcs.WCS(header=newheader).get_axis_types())
        except InconsistentAxisTypesError as err:
            projection = re.findall(r'expected [^,]+', str(err))[0][9:]
            newheader['CTYPE' + axis] = projection
        return newheader


def _wcs_slicer(wcs, missing_axes, item):
    """
    Returns the new sliced wcs and changed missing axis.

    Paramters
    ---------
    wcs: `astropy.wcs.WCS` or `ndcube.utils.wcs.WCS`
        WCS object to be sliced.

    missing_axes: `list` of `bool`
        Indicates which axes of the WCS are "missing", i.e. do not correspond to a data axis.

    item: `int`, `slice` or `tuple` of `int` and/or `slice`.
        Slicing item.  Note that unlike in other places in this package, the item has the
        same axis ordering as the WCS object, i.e. the reverse of the data order.

    Returns
    -------
    new_wcs: `astropy.wcs.WCS` or `ndcube.utils.wcs.WCS`
        Sliced WCS object.

    missing_axes: `list` of `bool`
        Altered missing axis list.  Note the ordering has been reversed to reflect the data
        (numpy) axis ordering convention.
    """
    # normal slice.
    item_checked = []
    if isinstance(item, slice):
        index = 0
        # creating a new tuple of slice where if the axis is dead i.e missing
        # then slice(0,1) added else slice(None, None, None) is appended and
        # if the check of missing_axes gives that this is the index where it
        # needs to be appended then it gets appended there.
        for _bool in missing_axes:
            if not _bool:
                if index != 1:
                    item_checked.append(item)
                    index += 1
                else:
                    item_checked.append(slice(None, None, None))
            else:
                item_checked.append(slice(0, 1))
        new_wcs = wcs.slice(item_checked)
    # item is int then slicing axis.
    elif isinstance(item, numbers.Integral):
        # using index to keep track of whether the int(which is converted to
        # slice(int_value, int_value+1)) is already added or not. It checks
        # the dead axis i.e missing_axes to check if it is dead than slice(0,1)
        # is appended in it. if the index value has reached 1 then the
        # slice(None, None, None) is added.
        index = 0
        for i, _bool in enumerate(missing_axes):
            if not _bool:
                if index != 1:
                    item_checked.append(slice(item, item + 1))
                    missing_axes[i] = True
                    index += 1
                else:
                    item_checked.append(slice(None, None, None))
            else:
                item_checked.append(slice(0, 1))
        new_wcs = wcs.slice(item_checked)
    # if it a tuple like [0:2, 0:3, 2] or [0:2, 1:3]
    elif isinstance(item, tuple):
        # Ellipsis slicing is currently not supported.
        # Raise an error if user tries to slice by ellipsis.
        if Ellipsis in item:
            raise NotImplementedError("Slicing FITS-WCS by ellipsis not supported.")
        # this is used to not exceed the range of the item tuple
        # if the check of the missing_axes which is False if not dead
        # is a success than the the item of the tuple is added one by
        # one and if the end of tuple is reached than slice(None, None, None)
        # is appended.
        index = 0
        for _bool in missing_axes:
            if not _bool:
                if index is not len(item):
                    item_checked.append(item[index])
                    index += 1
                else:
                    item_checked.append(slice(None, None, None))
            else:
                item_checked.append(slice(0, 1))
        # if all are slice in the item tuple
        if _all_slice(item_checked):
            new_wcs = wcs.slice(item_checked)
        # if all are not slices some of them are int then
        else:
            # this will make all the item in item_checked as slice.
            item_ = _slice_list(item_checked)
            new_wcs = wcs.slice(item_)
            for i, it in enumerate(item_checked):
                # If an axis is sliced out, i.e. it's item is an int,
                # set missing axis to True.
                # numbers.Integral captures all int types, int, np.int64, etc.
                if isinstance(it, numbers.Integral):
                    missing_axes[i] = True
    else:
        raise NotImplementedError("Slicing FITS-WCS by {} not supported.".format(type(item)))
    # returning the reverse list of missing axis as in the item here was reverse of
    # what was inputed so we had a reverse missing_axes.
    return new_wcs, missing_axes[::-1]


def _all_slice(obj):
    """
    Returns True if all the elements in the object are slices else return
    False.
    """
    result = False
    if not isinstance(obj, (tuple, list)):
        return result
    result |= all(isinstance(o, slice) for o in obj)
    return result


def _slice_list(obj):
    """
    Return list of all the slices.

    Example
    -------
    >>> _slice_list((slice(1,2), slice(1,3), 2, slice(2,4), 8))
    [slice(1, 2, None), slice(1, 3, None), slice(2, 3, None), slice(2, 4, None), slice(8, 9, None)]
    """
    result = []
    if not isinstance(obj, (tuple, list)):
        return result
    for i, o in enumerate(obj):
        if isinstance(o, int):
            result.append(slice(o, o + 1))
        elif isinstance(o, slice):
            result.append(o)
    return result


def reindex_wcs(wcs, inds):
    # From astropy.spectral_cube.wcs_utils
    """
    Re-index a WCS given indices.  The number of axes may be reduced.

    Parameters
    ----------
    wcs: sunpy.wcs.wcs.WCS
        The WCS to be manipulated
    inds: np.array(dtype='int')
        The indices of the array to keep in the output.
        e.g. swapaxes: [0,2,1,3]
        dropaxes: [0,1,3]
    """

    if not isinstance(inds, np.ndarray):
        raise TypeError("Indices must be an ndarray")

    if inds.dtype.kind != 'i':
        raise TypeError('Indices must be integers')

    outwcs = WCS(naxis=len(inds))
    wcs_params_to_preserve = ['cel_offset', 'dateavg', 'dateobs', 'equinox',
                              'latpole', 'lonpole', 'mjdavg', 'mjdobs', 'name',
                              'obsgeo', 'phi0', 'radesys', 'restfrq',
                              'restwav', 'specsys', 'ssysobs', 'ssyssrc',
                              'theta0', 'velangl', 'velosys', 'zsource']
    for par in wcs_params_to_preserve:
        setattr(outwcs.wcs, par, getattr(wcs.wcs, par))

    cdelt = wcs.wcs.cdelt

    try:
        outwcs.wcs.pc = wcs.wcs.pc[inds[:, None], inds[None, :]]
    except AttributeError:
        outwcs.wcs.pc = np.eye(wcs.naxis)

    outwcs.wcs.crpix = wcs.wcs.crpix[inds]
    outwcs.wcs.cdelt = cdelt[inds]
    outwcs.wcs.crval = wcs.wcs.crval[inds]
    outwcs.wcs.cunit = [wcs.wcs.cunit[i] for i in inds]
    outwcs.wcs.ctype = [wcs.wcs.ctype[i] for i in inds]
    outwcs.wcs.cname = [wcs.wcs.cname[i] for i in inds]
    outwcs._naxis = [wcs._naxis[i] for i in inds]

    return outwcs


def get_dependent_data_axes(wcs_object, data_axis, missing_axes):
    """
    Given a data axis index, return indices of dependent data axes.

    Both input and output axis indices are in the numpy ordering convention
    (reverse of WCS ordering convention). The returned axis indices include the input axis.
    Returned axis indices do NOT include any WCS axes that do not have a
    corresponding data axis, i.e. "missing" axes.

    Parameters
    ----------
    wcs_object: `astropy.wcs.WCS` or `ndcube.utils.wcs.WCS`
        The WCS object describing the axes.

    data_axis: `int`
        Index of axis (in numpy ordering convention) for which dependent axes are desired.

    missing_axes: iterable of `bool`
        Indicates which axes of the WCS are "missing", i.e. do not correspond to a data axis.

    Returns
    -------
    dependent_data_axes: `tuple` of `int`
        Sorted indices of axes dependent on input data_axis in numpy ordering convention.
    """
    # In order to correctly account for "missing" axes in this process,
    # we must determine what axes are dependent based on WCS axis indices.
    # Convert input data axis index to WCS axis index.
    wcs_axis = utils_cube.data_axis_to_wcs_axis(data_axis, missing_axes)
    # Determine dependent axes, including "missing" axes, using WCS ordering.
    wcs_dependent_axes = np.asarray(get_dependent_wcs_axes(wcs_object, wcs_axis))
    # Remove "missing" axes from output.
    non_missing_wcs_dependent_axes = wcs_dependent_axes[
        np.invert(missing_axes)[wcs_dependent_axes]]
    # Convert dependent axes back to numpy/data ordering.
    dependent_data_axes = tuple(np.sort([utils_cube.wcs_axis_to_data_axis(i, missing_axes)
                                         for i in non_missing_wcs_dependent_axes]))
    return dependent_data_axes


def get_dependent_wcs_axes(wcs_object, wcs_axis):
    """
    Given a WCS axis index, return indices of dependent WCS axes.

    Both input and output axis indices are in the WCS ordering convention
    (reverse of numpy ordering convention). The returned axis indices include the input axis.
    Returned axis indices DO include WCS axes that do not have a
    corresponding data axis, i.e. "missing" axes.

    Parameters
    ----------
    wcs_object: `astropy.wcs.WCS` or `ndcube.utils.wcs.WCS`
        The WCS object describing the axes.

    wcs_axis: `int`
        Index of axis (in WCS ordering convention) for which dependent axes are desired.

    Returns
    -------
    dependent_data_axes: `tuple` of `int`
        Sorted indices of axes dependent on input data_axis in WCS ordering convention.
    """
    # Pre-compute dependent axes. The matrix returned by
    # axis_correlation_matrix is (n_world, n_pixel) but we want to know
    # which pixel coordinates are linked to which other pixel coordinates.
    # So to do this we take a column from the matrix and find if there are
    # any entries in common with all other columns in the matrix.
    matrix = axis_correlation_matrix(wcs_object)
    world_dep = matrix[:, wcs_axis:wcs_axis + 1]
    dependent_wcs_axes = tuple(np.sort(np.nonzero((world_dep & matrix).any(axis=0))[0]))
    return dependent_wcs_axes


def axis_correlation_matrix(wcs_object):
    """
    Return True/False matrix indicating which WCS axes are dependent on others.

    Parameters
    ----------
    wcs_object: `astropy.wcs.WCS` or `ndcube.utils.wcs.WCS`
        The WCS object describing the axes.

    Returns
    -------
    matrix: `numpy.ndarray` of `bool`
        Square True/False matrix indicating which axes are dependent.
        For example, whether WCS axis 0 is dependent on WCS axis 1 is given by matrix[0, 1].
    """
    n_world = len(wcs_object.wcs.ctype)
    n_pixel = wcs_object.naxis

    # If there are any distortions present, we assume that there may be
    # correlations between all axes. Maybe if some distortions only apply
    # to the image plane we can improve this
    for distortion_attribute in ('sip', 'det2im1', 'det2im2'):
        if getattr(wcs_object, distortion_attribute):
            return np.ones((n_world, n_pixel), dtype=bool)

    # Assuming linear world coordinates along each axis, the correlation
    # matrix would be given by whether or not the PC matrix is zero
    matrix = wcs_object.wcs.get_pc() != 0

    # We now need to check specifically for celestial coordinates since
    # these can assume correlations because of spherical distortions. For
    # each celestial coordinate we copy over the pixel dependencies from
    # the other celestial coordinates.
    celestial = (wcs_object.wcs.axis_types // 1000) % 10 == 2
    celestial_indices = np.nonzero(celestial)[0]
    for world1 in celestial_indices:
        for world2 in celestial_indices:
            if world1 != world2:
                matrix[world1] |= matrix[world2]
                matrix[world2] |= matrix[world1]

    return matrix


def append_sequence_axis_to_wcs(wcs_object):
    """
    Appends a 1-to-1 dummy axis to a WCS object.
    """
    dummy_number = wcs_object.naxis + 1
    wcs_header = wcs_object.to_header()
    wcs_header.append((f"CTYPE{dummy_number}", "ITER",
                       "A unitless iteration-by-one axis."))
    wcs_header.append((f"CRPIX{dummy_number}", 0.,
                       "Pixel coordinate of reference point"))
    wcs_header.append((f"CDELT{dummy_number}", 1.,
                       "Coordinate increment at reference point"))
    wcs_header.append((f"CRVAL{dummy_number}", 0.,
                       "Coordinate value at reference point"))
    wcs_header.append((f"CUNIT{dummy_number}", "pix",
                       "Coordinate value at reference point"))
    wcs_header["WCSAXES"] = dummy_number
    return WCS(wcs_header)


def convert_between_array_and_pixel_axes(axis, naxes):
    """Reflects axis index about center of number of axes.

    This is used to convert between array axes in numpy order and pixel axes in WCS order.
    Works in both directions.

    Parameters
    ----------
    axis: `numpy.ndarray` of `int`
        The axis number(s) before reflection.

    naxes: `int`
        The number of array axes.

    Returns
    -------
    reflected_axis: `numpy.ndarray` of `int`
        The axis number(s) after reflection.
    """
    # Check type of input.
    if not isinstance(axis, np.ndarray):
        raise TypeError("input must be of array type. Got type: {type(axis)}")
    if axis.dtype.char not in np.typecodes['AllInteger']:
        raise TypeError("input dtype must be of int type.  Got dtype: {axis.dtype})")
    # Convert negative indices to positive equivalents.
    axis[axis < 0] += naxes
    if any(axis > naxes - 1):
        raise IndexError("Axis out of range.  "
                         f"Number of axes = {naxes}; Axis numbers requested = {axes}")
    # Reflect axis about center of number of axes.
    reflected_axis = naxes - 1 - axis

    return reflected_axis


def pixel_axis_to_world_axes(pixel_axis, axis_correlation_matrix):
    """
    Retrieves the indices of the world axis physical types corresponding to a pixel axis.

    Parameters
    ----------
    pixel_axis: `int`
        The pixel axis index/indices for which the world axes are desired.

    axis_correlation_matrix: `numpy.ndarray` of `bool`
        2D boolean correlation matrix defining the dependence between the pixel and world axes.
        Format same as `astropy.wcs.BaseLowLevelWCS.axis_correlation_matrix`.

    Returns
    -------
    world_axes: `numpy.ndarray`
        The world axis indices corresponding to the pixel axis.
    """
    return np.arange(axis_correlation_matrix.shape[0])[axis_correlation_matrix[:, pixel_axis]]


def physical_type_to_world_axis(physical_type, world_axis_physical_types):
    """
    Returns world axis index of a physical type based on WCS world_axis_physical_types.

    Input can be a substring of a physical type, so long as it is unique.

    Parameters
    ----------
    physical_type: `str`
        The physical type or a substring unique to a physical type.

    world_axis_physical_types: sequence of `str`
        All available physical types.  Ordering must be same as
        `astropy.wcs.BaseLowLevelWCS.world_axis_physical_types`

    Returns
    -------
    world_axis: `numbers.Integral`
        The world axis index of the physical type.
    """
    # Find world axis index described by physical type.
    widx = np.where(world_axis_physical_types == physical_type)[0]
    # If physical type does not correspond to entry in world_axis_physical_types,
    # check if it is a substring of any physical types.
    if len(widx) == 0:
        widx = [physical_type in world_axis_physical_type
                for world_axis_physical_type in world_axis_physical_types]
        widx = np.arange(len(world_axis_physical_types))[widx]
    if len(widx) != 1:
        raise ValueError(
                "Input does not uniquely correspond to a physical type."
                f" Expected unique substring of one of {world_axis_physical_types}."
                f"  Got: {physical_type}")
    # Return axes with duplicates removed.
    return widx[0]


def reduced_axis_correlation_matrix(axis_correlation_matrix, missing_axes,
                                    return_world_indices=False):
    """
    Return axis correlation matrix with missing axes removed.

    This is needed because ndcube 1.3.x does not use astropy.nddata to slice WCSs.
    Will be removed in ndcube 2.0.

    Parameters
    ----------
    axis_correlation_matrix: `numpy.ndarray` of `bool`
        2D boolean correlation matrix defining the dependence between the pixel and world axes.
        Format same as `astropy.wcs.BaseLowLevelWCS.axis_correlation_matrix`.

    missing_axes: `list` of `bool`
        Denotes axes in WCS for which the corresponding data axis is missing.

    return_world_indices: `bool`
        If True, the indices of the world_axis_physical_types corresponding to the
        reduced matrix are returned.
        Default=False

    Returns
    -------
    reduced_matrix: `numpy.ndarray` of `bool`
        axis_correlation_matrix with missing axes removed.
    """
    # Remove missing pixel axes
    pixel_axes = np.invert(missing_axes)
    reduced_matrix = axis_correlation_matrix[:, pixel_axes]
    # Remove world axes which now no longer correspond to a pixel axis.
    world_axes = [reduced_matrix[i].any() for i in range(axis_correlation_matrix.shape[0])]
    reduced_matrix = reduced_matrix[world_axes]
    if return_world_indices:
        return reduced_matrix, world_axes
    else:
        return reduced_matrix


def reduced_correlation_matrix_and_world_physical_types(
        axis_correlation_matrix, world_axis_physical_types, missing_axes):
    """
    Return axis correlation matrix with missing axes removed.

    This is needed because ndcube 1.3.x does not use astropy.nddata to slice WCSs.
    Will be removed in ndcube 2.0.

    Parameters
    ----------
    axis_correlation_matrix: `numpy.ndarray` of `bool`
        2D boolean correlation matrix defining the dependence between the pixel and world axes.
        Format same as `astropy.wcs.BaseLowLevelWCS.axis_correlation_matrix`.

    world_axis_physical_types: iterable of `str`
        The physical types corresponding to the world axes of the axis correlation matrix.

    missing_axes: `list` of `bool`
        Denotes axes in WCS for which the corresponding data axis is missing.

    Returns
    -------
    reduced_matrix: `numpy.ndarray` of `bool`
        axis_correlation_matrix with missing axes removed.

    reduced_physical_types: `numpy.ndarray` of `str`
        The physical types corresponding to the reduced matrix.
    """
    reduced_matrix, world_axes = reduced_axis_correlation_matrix(
            axis_correlation_matrix, missing_axes, return_world_indices=True)
    reduced_physical_types = np.array(world_axis_physical_types)[world_axes]
    return reduced_matrix, reduced_physical_types
