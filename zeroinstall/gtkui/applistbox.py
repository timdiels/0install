"""A GTK dialog which displays a list of Zero Install applications in the menu."""
# Copyright (C) 2008, Thomas Leonard
# See the README file for details, or visit http://0install.net.

import os
import gtk, gobject
import gtk.glade
import subprocess

from zeroinstall.gtkui import icon, xdgutils, treetips

def _pango_escape(s):
	return s.replace('&', '&amp;').replace('<', '&lt;')

class AppList:
	"""A list of applications which can be displayed in an L{AppListBox}.
	For example, a program might implement this to display a list of plugins.
	This default implementation lists applications in the freedesktop.org menus.
	"""
	def get_apps(self):
		"""Return a list of application URIs."""
		self.apps = xdgutils.discover_existing_apps()
		return self.apps.keys()

	def remove_app(self, uri):
		"""Remove this application from the list."""
		path = self.apps[uri]
		os.unlink(path)

_tooltips = {
	0: "Run the application",
	1: "Show documentation files",
	2: "Upgrade or change versions",
	3: "Remove launcher from the menu",
}

class AppListBox:
	"""A dialog box which lists applications already added to the menus."""
	ICON, URI, NAME, MARKUP = range(4)

	def __init__(self, iface_cache, app_list):
		"""Constructor.
		@param iface_cache: used to find extra information about programs
		@type iface_cache: L{zeroinstall.injector.iface_cache.IfaceCache}
		@param app_list: used to list or remove applications
		@type app_list: L{AppList}
		"""
		gladefile = os.path.join(os.path.dirname(__file__), 'desktop.glade')
		self.iface_cache = iface_cache
		self.app_list = app_list

		widgets = gtk.glade.XML(gladefile, 'applist')
		self.window = widgets.get_widget('applist')
		tv = widgets.get_widget('treeview')

		self.model = gtk.ListStore(gtk.gdk.Pixbuf, str, str, str)

		self.populate_model()
		tv.set_model(self.model)
		tv.get_selection().set_mode(gtk.SELECTION_NONE)

		cell_icon = gtk.CellRendererPixbuf()
		cell_icon.set_property('xpad', 4)
		cell_icon.set_property('ypad', 4)
		column = gtk.TreeViewColumn('Icon', cell_icon, pixbuf = AppListBox.ICON)
		tv.append_column(column)

		cell_text = gtk.CellRendererText()
		column = gtk.TreeViewColumn('Name', cell_text, markup = AppListBox.MARKUP)
		tv.append_column(column)

		cell_actions = ActionsRenderer(self, tv)
		actions_column = gtk.TreeViewColumn('Actions', cell_actions, uri = AppListBox.URI)
		tv.append_column(actions_column)

		def redraw_actions(path):
			if path is not None:
				area = tv.get_cell_area(path, actions_column)
				tv.queue_draw_area(*area)

		tips = treetips.TreeTips()
		def motion(widget, mev):
			if mev.window == tv.get_bin_window():
				new_hover = (None, None, None)
				pos = tv.get_path_at_pos(int(mev.x), int(mev.y))
				if pos:
					path, col, x, y = pos
					if col == actions_column:
						area = tv.get_cell_area(path, col)
						iface = self.model[path][AppListBox.URI]
						action = cell_actions.get_action(area, x, y)
						if action is not None:
							new_hover = (path, iface, action)
				if new_hover != cell_actions.hover:
					redraw_actions(cell_actions.hover[0])
					cell_actions.hover = new_hover
					redraw_actions(cell_actions.hover[0])
					tips.prime(tv, _tooltips.get(cell_actions.hover[2], None))
		tv.connect('motion-notify-event', motion)

		def leave(widget, lev):
			redraw_actions(cell_actions.hover[0])
			cell_actions.hover = (None, None, None)
			tips.hide()

		tv.connect('leave-notify-event', leave)

		self.model.set_sort_column_id(AppListBox.NAME, gtk.SORT_ASCENDING)

		show_cache = widgets.get_widget('show_cache')
		self.window.action_area.set_child_secondary(show_cache, True)

		def response(box, resp):
			if resp == 0:
				subprocess.Popen(['0store', 'manage'])
			else:
				box.destroy()
		self.window.connect('response', response)

	def populate_model(self):
		model = self.model
		model.clear()

		for uri in self.app_list.get_apps():
			itr = model.append()
			model[itr][AppListBox.URI] = uri

			iface = self.iface_cache.get_interface(uri)
			name = iface.get_name()
			summary = iface.summary or 'No information available'
			summary = summary[:1].capitalize() + summary[1:]

			model[itr][AppListBox.NAME] = name
			pixbuf = icon.load_icon(self.iface_cache.get_icon_path(iface))
			if not pixbuf:
				pixbuf = self.window.render_icon(gtk.STOCK_EXECUTE, gtk.ICON_SIZE_DIALOG)
			model[itr][AppListBox.ICON] = pixbuf

			model[itr][AppListBox.MARKUP] = '<b>%s</b>\n<i>%s</i>' % (_pango_escape(name), _pango_escape(summary))

	def action_run(self, uri):
		subprocess.Popen(['0launch', '--', uri])

	def action_help(self, uri):
		from zeroinstall.injector import policy, reader, model
		p = policy.Policy(uri)
		policy.network_use = model.network_offline
		if p.need_download():
			child = subprocess.Popen(['0launch', '-d', '--', uri])
			child.wait()
			if child.returncode:
				return
		iface = self.iface_cache.get_interface(uri)
		reader.update_from_cache(iface)
		p.solve_with_downloads()
		impl = p.solver.selections[iface]
		assert impl, "Failed to choose an implementation of " + uri
		help_dir = impl.metadata.get('doc-dir')
		path = p.get_implementation_path(impl)
		assert path, "Chosen implementation is not cached!"
		if help_dir:
			path = os.path.join(path, help_dir)
		else:
			main = impl.main
			if main:
				# Hack for ROX applications. They should be updated to
				# set doc-dir.
				help_dir = os.path.join(path, os.path.dirname(main), 'Help')
				if os.path.isdir(help_dir):
					path = help_dir

		# xdg-open has no "safe" mode, so check we're not "opening" an application.
		if os.path.exists(os.path.join(path, 'AppRun')):
			raise Exception("Documentation directory '%s' is an AppDir; refusing to open" % path)

		subprocess.Popen(['xdg-open', path])

	def action_properties(self, uri):
		subprocess.Popen(['0launch', '--gui', '--', uri])

	def action_remove(self, uri):
		name = self.iface_cache.get_interface(uri).get_name()

		box = gtk.MessageDialog(self.window, gtk.DIALOG_MODAL, gtk.MESSAGE_QUESTION, gtk.BUTTONS_CANCEL, "")
		box.set_markup("Remove <b>%s</b> from the menu?" % _pango_escape(name))
		box.add_button(gtk.STOCK_DELETE, gtk.RESPONSE_OK)
		box.set_default_response(gtk.RESPONSE_OK)
		resp = box.run()
		box.destroy()
		if resp == gtk.RESPONSE_OK:
			try:
				self.app_list.remove_app(uri)
			except Exception, ex:
				box = gtk.MessageDialog(self.window, gtk.DIALOG_MODAL, gtk.MESSAGE_ERROR, gtk.BUTTONS_OK, "Failed to remove %s: %s" % (name, ex))
				box.run()
				box.destroy()
			self.populate_model()

class ActionsRenderer(gtk.GenericCellRenderer):
	__gproperties__ = {
		"uri": (gobject.TYPE_STRING, "Text", "Text", "-", gobject.PARAM_READWRITE),
	}

	def __init__(self, applist, widget):
		"@param widget: widget used for style information"
		gtk.GenericCellRenderer.__init__(self)
		self.set_property('mode', gtk.CELL_RENDERER_MODE_ACTIVATABLE)
		self.padding = 4

		self.applist = applist

		self.size = 10
		def stock_lookup(name):
			pixbuf = widget.render_icon(name, gtk.ICON_SIZE_BUTTON)
			self.size = max(self.size, pixbuf.get_width(), pixbuf.get_height())
			return pixbuf

		if hasattr(gtk, 'STOCK_MEDIA_PLAY'):
			self.run = stock_lookup(gtk.STOCK_MEDIA_PLAY)
		else:
			self.run = stock_lookup(gtk.STOCK_YES)
		self.help = stock_lookup(gtk.STOCK_HELP)
		self.properties = stock_lookup(gtk.STOCK_PROPERTIES)
		self.remove = stock_lookup(gtk.STOCK_DELETE)
		self.hover = (None, None, None)	# Path, URI, action

	def do_set_property(self, prop, value):
		setattr(self, prop.name, value)

	def on_get_size(self, widget, cell_area, layout = None):
		total_size = self.size * 2 + self.padding * 4
		return (0, 0, total_size, total_size)

	def on_render(self, window, widget, background_area, cell_area, expose_area, flags):
		hovering = self.uri == self.hover[1]

		s = self.size

		cx = cell_area.x + self.padding
		cy = cell_area.y + (cell_area.height / 2) - s - self.padding

		ss = s + self.padding * 2

		b = 0
		for (x, y), icon in [((0, 0), self.run),
			     ((ss, 0), self.help),
			     ((0, ss), self.properties),
			     ((ss, ss), self.remove)]:
			if hovering and b == self.hover[2]:
				widget.style.paint_box(window, gtk.STATE_NORMAL, gtk.SHADOW_OUT,
						expose_area, widget, None,
						cx + x - 2, cy + y - 2, s + 4, s + 4)

			window.draw_pixbuf(widget.style.white_gc, icon,
						0, 0,		# Source x,y
						cx + x, cy + y)
			b += 1

	def on_activate(self, event, widget, path, background_area, cell_area, flags):
		if event.type != gtk.gdk.BUTTON_PRESS:
			return False
		action = self.get_action(cell_area, event.x - cell_area.x, event.y - cell_area.y)
		if action == 0:
			self.applist.action_run(self.uri)
		elif action == 1:
			self.applist.action_help(self.uri)
		elif action == 2:
			self.applist.action_properties(self.uri)
		elif action == 3:
			self.applist.action_remove(self.uri)

	def get_action(self, area, x, y):
		lower = int(y > (area.height / 2)) * 2

		s = self.size + self.padding * 2
		if x > s * 2:
			return None
		return int(x > s) + lower

if gtk.pygtk_version < (2, 8, 0):
	# Note sure exactly which versions need this.
	# 2.8.0 gives a warning if you include it, though.
	gobject.type_register(ActionsRenderer)
