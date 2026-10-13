"""NFO generation service for Jellyfin/Emby compatibility."""

import json
import xml.etree.ElementTree as ET
from datetime import datetime
from xml.dom import minidom

from server.models.nfo import EpisodeNFO, SeasonNFO, TVShowNFO
from server.models.tmdb import TMDBEpisode, TMDBSeason, TMDBSeries

XML_DECLARATION = '<?xml version="1.0" encoding="utf-8" standalone="yes"?>'


class NFOService:
    """Service for generating NFO files."""

    def _prettify(self, elem: ET.Element) -> str:
        """
        Return a pretty-printed XML string with proper indentation.

        Args:
            elem: XML element to prettify.

        Returns:
            Pretty-printed XML string with declaration.
        """
        rough_string = ET.tostring(elem, encoding="unicode")
        reparsed = minidom.parseString(rough_string)
        # Get pretty XML without the default declaration
        pretty_xml = reparsed.toprettyxml(indent="  ", encoding=None)
        # Remove the default declaration added by minidom
        lines = pretty_xml.split("\n")
        if lines[0].startswith("<?xml"):
            lines = lines[1:]
        # Remove empty lines
        lines = [line for line in lines if line.strip()]
        return XML_DECLARATION + "\n" + "\n".join(lines)

    def _add_element(
        self,
        parent: ET.Element,
        tag: str,
        text: str | None,
    ) -> ET.Element | None:
        """Add child element if text is not None/empty."""
        if text is not None and str(text).strip():
            elem = ET.SubElement(parent, tag)
            elem.text = str(text)
            return elem
        return None

    def generate_tvshow_nfo(self, data: TVShowNFO) -> str:
        """
        Generate tvshow.nfo XML content.

        Args:
            data: TVShow NFO data.

        Returns:
            XML string for tvshow.nfo.
        """
        root = ET.Element("tvshow")

        # ElementTree 统一转义 XML 文本，避免实体再次塞入 CDATA 后被当作原文。
        if data.plot:
            plot_elem = ET.SubElement(root, "plot")
            plot_elem.text = data.plot
            outline_elem = ET.SubElement(root, "outline")
            outline_elem.text = data.plot

        # lockdata
        self._add_element(root, "lockdata", "false")

        # dateadded
        self._add_element(root, "dateadded", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        # title
        self._add_element(root, "title", data.title)

        # originaltitle
        self._add_element(root, "originaltitle", data.original_title)

        # rating
        if data.rating is not None:
            self._add_element(root, "rating", f"{data.rating:.1f}")

        # year
        if data.year is not None:
            self._add_element(root, "year", str(data.year))

        # sorttitle
        self._add_element(root, "sorttitle", data.sort_title or data.title)

        # tmdbid
        if data.tmdb_id is not None and data.tmdb_id > 0:
            self._add_element(root, "tmdbid", str(data.tmdb_id))

        # premiered 和 releasedate
        if data.premiered is not None:
            self._add_element(root, "premiered", data.premiered.isoformat())
            self._add_element(root, "releasedate", data.premiered.isoformat())

        # genres
        for genre in data.genres:
            self._add_element(root, "genre", genre)

        # uniqueid
        if data.tmdb_id is not None and data.tmdb_id > 0:
            uniqueid = ET.SubElement(root, "uniqueid", type="tmdb")
            uniqueid.text = str(data.tmdb_id)

        if data.anilist_id is not None and data.anilist_id > 0:
            uniqueid = ET.SubElement(root, "uniqueid", type="anilist")
            uniqueid.text = str(data.anilist_id)

        # episodeguide
        if data.tmdb_id is not None and data.tmdb_id > 0:
            self._add_element(root, "episodeguide", json.dumps({"tmdb": str(data.tmdb_id)}))

        # season 和 episode 固定为 -1
        self._add_element(root, "season", "-1")
        self._add_element(root, "episode", "-1")

        # displayorder
        self._add_element(root, "displayorder", "aired")

        # status
        self._add_element(root, "status", data.status)

        return self._prettify(root)

    def generate_season_nfo(self, data: SeasonNFO) -> str:
        """
        Generate season.nfo XML content.

        Args:
            data: Season NFO data.

        Returns:
            XML string for season.nfo.
        """
        root = ET.Element("season")

        # plot 和 outline（可为空）
        plot_elem = ET.SubElement(root, "plot")
        plot_elem.text = data.plot or ""
        outline_elem = ET.SubElement(root, "outline")
        outline_elem.text = data.plot or ""

        # lockdata
        self._add_element(root, "lockdata", "false")

        # dateadded
        self._add_element(root, "dateadded", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        # title
        self._add_element(root, "title", data.title or f"Season {data.season_number}")

        # year
        if data.premiered:
            self._add_element(root, "year", str(data.premiered.year))

        # sorttitle
        self._add_element(root, "sorttitle", data.title or f"Season {data.season_number}")

        # premiered 和 releasedate
        if data.premiered is not None:
            self._add_element(root, "premiered", data.premiered.isoformat())
            self._add_element(root, "releasedate", data.premiered.isoformat())

        # seasonnumber
        self._add_element(root, "seasonnumber", str(data.season_number))

        return self._prettify(root)

    def generate_episode_nfo(self, data: EpisodeNFO) -> str:
        """
        Generate episode.nfo XML content.

        Args:
            data: Episode NFO data.

        Returns:
            XML string for episode.nfo.
        """
        root = ET.Element("episodedetails")

        self._add_element(root, "title", data.title)
        self._add_element(root, "season", str(data.season))
        self._add_element(root, "episode", str(data.episode))
        self._add_element(root, "plot", data.plot)

        if data.aired is not None:
            self._add_element(root, "aired", data.aired.isoformat())

        if data.rating is not None:
            self._add_element(root, "rating", f"{data.rating:.1f}")

        return self._prettify(root)

    # Conversion methods from TMDB models

    def tvshow_from_tmdb(self, series: TMDBSeries) -> TVShowNFO:
        """
        Convert TMDB series to TVShowNFO.

        Args:
            series: TMDB series data.

        Returns:
            TVShowNFO data model.
        """
        year = None
        if series.first_air_date:
            year = series.first_air_date.year

        return TVShowNFO(
            title=series.name,
            original_title=series.original_name,
            sort_title=series.name,
            rating=series.vote_average,
            year=year,
            plot=series.overview,
            tmdb_id=series.id if series.id > 0 and series.metadata_source == "tmdb" else None,
            anilist_id=series.anilist_id,
            genres=series.genres,
            premiered=series.first_air_date,
            status=series.status,
        )

    def season_from_tmdb(self, season: TMDBSeason) -> SeasonNFO:
        """
        Convert TMDB season to SeasonNFO.

        Args:
            season: TMDB season data.

        Returns:
            SeasonNFO data model.
        """
        return SeasonNFO(
            season_number=season.season_number,
            title=season.name,
            plot=season.overview,
            premiered=season.air_date,
        )

    def episode_from_tmdb(
        self,
        episode: TMDBEpisode,
        season_number: int,
    ) -> EpisodeNFO:
        """
        Convert TMDB episode to EpisodeNFO.

        Args:
            episode: TMDB episode data.
            season_number: Season number for this episode.

        Returns:
            EpisodeNFO data model.
        """
        return EpisodeNFO(
            title=episode.name,
            season=season_number,
            episode=episode.episode_number,
            plot=episode.overview,
            aired=episode.air_date,
            rating=episode.vote_average,
        )
